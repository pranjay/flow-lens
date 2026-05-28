"""
tests/test_pipeline.py

Unit tests for the three core stages:
  - OptionsTransformer (parsing + filtering)
  - BiasEngine (aggregation + dominant contract)
  - PersistenceTracker (consecutive day counting)

Run with:  python -m pytest tests/ -v
"""
import json
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

# Make sure project root is on the path when running tests directly
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import OptionsFilterConfig
from data.transformer import OptionsTransformer
from models.options import OptionContract, TickerBias
from signals.bias_engine import BiasEngine
from signals.persistence import PersistenceTracker


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_FILE = Path(__file__).parent / "sample_response.json"

@pytest.fixture
def raw_rows():
    with open(SAMPLE_FILE) as f:
        return json.load(f)["data"]

@pytest.fixture
def permissive_cfg():
    """Config that passes all sample rows through."""
    return OptionsFilterConfig(
        min_vol_oi_ratio  = 1.0,
        min_dte           = 1,
        max_dte           = 400,
        min_premium_usd   = 0,
        min_last_price    = 0,
    )

@pytest.fixture
def strict_cfg():
    """Default production config."""
    return OptionsFilterConfig()   # uses all the hardened defaults

@pytest.fixture
def contracts(raw_rows, permissive_cfg):
    return OptionsTransformer(permissive_cfg).transform_all(raw_rows)


# ---------------------------------------------------------------------------
# OptionsTransformer tests
# ---------------------------------------------------------------------------

class TestOptionsTransformer:

    def test_parses_all_sample_rows(self, raw_rows, permissive_cfg):
        contracts = OptionsTransformer(permissive_cfg).transform_all(raw_rows)
        assert len(contracts) == 5

    def test_vol_oi_ratio_calculated(self, contracts):
        nvda = next(c for c in contracts if c.ticker == "NVDA" and c.strike == 160.0)
        # 45000 / 4200 ≈ 10.71
        assert nvda.vol_oi_ratio == pytest.approx(10.71, abs=0.1)

    def test_premium_calculated(self, contracts):
        nvda = next(c for c in contracts if c.ticker == "NVDA" and c.strike == 160.0)
        # 45000 × 8.80 × 100 = 39,600,000
        assert nvda.premium_usd == pytest.approx(39_600_000, rel=0.01)

    def test_expiration_label_format(self, contracts):
        nvda = next(c for c in contracts if c.ticker == "NVDA" and c.strike == 160.0)
        # Label must be DDMmmYY format — e.g. "21JUN26"
        label = nvda.expiration_label
        assert len(label) == 7
        assert label[:2].isdigit()          # day
        assert label[2:5].isalpha()         # month abbreviation
        assert label[5:].isdigit()          # 2-digit year

    def test_type_normalisation(self, contracts):
        calls = [c for c in contracts if c.is_call]
        puts  = [c for c in contracts if c.is_put]
        assert len(calls) == 3   # NVDA 160C, NVDA 165C, TSLA 300C
        assert len(puts)  == 2   # AAPL 190P, SPY 520P

    def test_strict_filter_excludes_low_ratio(self, raw_rows):
        """With strict config (vol/OI ≥ 5x) all sample rows should still pass
        since sample data was crafted with ratios of 5.6x–10.7x."""
        contracts = OptionsTransformer(OptionsFilterConfig()).transform_all(raw_rows)
        # SPY is an ETF (baseSymbolType=2) but transformer doesn't filter by type
        # All 5 sample contracts have vol/OI > 5 — all should pass
        assert len(contracts) == 5


# ---------------------------------------------------------------------------
# BiasEngine tests
# ---------------------------------------------------------------------------

class TestBiasEngine:

    def test_nvda_is_long(self, contracts):
        engine = BiasEngine()
        biases = engine.compute([c for c in contracts if c.ticker == "NVDA"])
        nvda   = biases[0]
        assert nvda.ticker == "NVDA"
        assert nvda.bias   == "Long"

    def test_parity_ratio(self, contracts):
        engine = BiasEngine()
        biases = engine.compute([c for c in contracts if c.ticker == "NVDA"])
        nvda   = biases[0]
        # 2 call contracts only → parity = inf (or very high)
        assert nvda.parity > 1

    def test_dominant_contract_is_highest_premium(self, contracts):
        engine = BiasEngine()
        biases = engine.compute([c for c in contracts if c.ticker == "NVDA"])
        nvda   = biases[0]
        dom    = nvda.dominant_contract
        assert dom is not None
        # The 160C has higher premium (45000 × 8.80) vs 165C (22000 × 5.20)
        assert dom.strike == 160.0
        assert dom.option_type == "Call"

    def test_sorted_by_premium_descending(self, contracts):
        engine = BiasEngine()
        biases = engine.compute(contracts)
        premiums = [b.total_premium for b in biases]
        assert premiums == sorted(premiums, reverse=True)

    def test_aapl_is_short(self, contracts):
        engine = BiasEngine()
        biases = engine.compute([c for c in contracts if c.ticker == "AAPL"])
        aapl   = biases[0]
        assert aapl.bias == "Short"

    def test_total_contracts_count(self, contracts):
        engine = BiasEngine()
        biases = engine.compute(contracts)
        nvda   = next(b for b in biases if b.ticker == "NVDA")
        assert nvda.total_contracts == 2   # two NVDA rows in sample


# ---------------------------------------------------------------------------
# PersistenceTracker tests
# ---------------------------------------------------------------------------

class TestPersistenceTracker:

    def _make_bias(self, ticker: str, bias: str) -> TickerBias:
        b = TickerBias(ticker=ticker)
        # manually set bias direction via volume
        if bias == "Long":
            b.call_volume = 1000
            b.put_volume  = 100
        else:
            b.call_volume = 100
            b.put_volume  = 1000
        return b

    def test_first_day_is_one(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tracker = PersistenceTracker(Path(tmpdir))
            biases  = [self._make_bias("NVDA", "Long")]
            tracker.annotate(biases)
            assert biases[0].consecutive_days == 1

    def test_second_day_same_direction_is_two(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tracker = PersistenceTracker(Path(tmpdir))

            day1 = [self._make_bias("NVDA", "Long")]
            tracker.annotate(day1)

            day2 = [self._make_bias("NVDA", "Long")]
            tracker.annotate(day2)

            assert day2[0].consecutive_days == 2

    def test_direction_reversal_resets_to_one(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tracker = PersistenceTracker(Path(tmpdir))

            day1 = [self._make_bias("NVDA", "Long")]
            tracker.annotate(day1)

            day2 = [self._make_bias("NVDA", "Short")]
            tracker.annotate(day2)

            assert day2[0].consecutive_days == 1

    def test_three_day_streak(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tracker = PersistenceTracker(Path(tmpdir))
            for day in range(3):
                biases = [self._make_bias("TSLA", "Short")]
                tracker.annotate(biases)
            assert biases[0].consecutive_days == 3


# ---------------------------------------------------------------------------
# TickerBias signal_strength tests
# ---------------------------------------------------------------------------

class TestSignalStrength:

    def _bias(self, days: int, premium: float, parity: float) -> TickerBias:
        b = TickerBias(ticker="TEST")
        b.consecutive_days = days
        b.total_premium    = premium
        # set call/put to produce the desired parity
        b.call_volume = int(parity * 1000)
        b.put_volume  = 1000
        return b

    def test_strong_requires_3_days_and_1m_premium(self):
        b = self._bias(days=3, premium=1_500_000, parity=4.0)
        assert b.signal_strength == "Strong"

    def test_moderate_two_days(self):
        b = self._bias(days=2, premium=100_000, parity=3.0)
        assert b.signal_strength == "Moderate"

    def test_moderate_high_premium_one_day(self):
        b = self._bias(days=1, premium=750_000, parity=3.0)
        assert b.signal_strength == "Moderate"

    def test_weak_single_day_low_premium(self):
        b = self._bias(days=1, premium=50_000, parity=2.0)
        assert b.signal_strength == "Weak"
