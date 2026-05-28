"""tests/test_pipeline.py — Run with: python -m pytest tests/ -v"""
import json, sys, tempfile
from datetime import date, timedelta
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import OptionsFilterConfig
from data.transformer import OptionsTransformer
from models.options import OptionContract, TickerBias
from signals.bias_engine import BiasEngine
from signals.persistence import PersistenceTracker

SAMPLE = Path(__file__).parent / "sample_response.json"

@pytest.fixture
def raw_rows():
    with open(SAMPLE) as f:
        return json.load(f)["data"]

@pytest.fixture
def permissive_cfg():
    return OptionsFilterConfig(
        min_vol_oi_ratio=1.0, min_dte=1, max_dte=400,
        min_premium_usd=0,
    )

@pytest.fixture
def contracts(raw_rows, permissive_cfg):
    return OptionsTransformer(permissive_cfg).transform_all(raw_rows)


# ── Transformer ────────────────────────────────────────────────────────────────

class TestOptionsTransformer:

    def test_parses_all_sample_rows(self, raw_rows, permissive_cfg):
        assert len(OptionsTransformer(permissive_cfg).transform_all(raw_rows)) == 5

    def test_vol_oi_ratio_calculated(self, contracts):
        nvda = next(c for c in contracts if c.ticker == "NVDA" and c.strike == 160.0)
        assert nvda.vol_oi_ratio == pytest.approx(10.71, abs=0.1)

    def test_premium_uses_bid_ask_mid(self, contracts):
        nvda = next(c for c in contracts if c.ticker == "NVDA" and c.strike == 160.0)
        # mid = (8.50 + 9.00) / 2 = 8.75; premium = 45000 × 8.75 × 100
        assert nvda.premium_usd == pytest.approx(45000 * 8.75 * 100, rel=0.01)

    def test_delta_parsed(self, contracts):
        nvda = next(c for c in contracts if c.ticker == "NVDA" and c.strike == 160.0)
        assert nvda.delta == pytest.approx(0.42, abs=0.01)

    def test_moneyness_parsed(self, contracts):
        nvda = next(c for c in contracts if c.ticker == "NVDA" and c.strike == 160.0)
        assert nvda.moneyness == "OTM"

    def test_expiration_label_format(self, contracts):
        nvda = next(c for c in contracts if c.ticker == "NVDA" and c.strike == 160.0)
        label = nvda.expiration_label
        assert len(label) == 7
        assert label[:2].isdigit()
        assert label[2:5].isalpha()
        assert label[5:].isdigit()

    def test_type_normalisation(self, contracts):
        calls = [c for c in contracts if c.is_call]
        puts  = [c for c in contracts if c.is_put]
        assert len(calls) == 3
        assert len(puts)  == 2

    def test_strict_vol_oi_filter(self, raw_rows):
        # All sample rows have vol/OI > 5 — all pass strict config
        assert len(OptionsTransformer(OptionsFilterConfig()).transform_all(raw_rows)) == 5

    def test_volatility_as_decimal(self, contracts):
        nvda = next(c for c in contracts if c.ticker == "NVDA" and c.strike == 160.0)
        assert nvda.volatility == pytest.approx(0.452, abs=0.001)


# ── BiasEngine ─────────────────────────────────────────────────────────────────

class TestBiasEngine:

    def test_nvda_is_long(self, contracts):
        biases = BiasEngine().compute([c for c in contracts if c.ticker == "NVDA"])
        assert biases[0].bias == "Long"

    def test_aapl_is_short(self, contracts):
        biases = BiasEngine().compute([c for c in contracts if c.ticker == "AAPL"])
        assert biases[0].bias == "Short"

    def test_dominant_contract_is_highest_premium(self, contracts):
        biases = BiasEngine().compute([c for c in contracts if c.ticker == "NVDA"])
        dom = biases[0].dominant_contract
        assert dom is not None
        assert dom.strike == 160.0       # higher premium contract
        assert dom.delta  == pytest.approx(0.42, abs=0.01)
        assert dom.moneyness == "OTM"

    def test_sorted_by_premium_descending(self, contracts):
        biases = BiasEngine().compute(contracts)
        premiums = [b.total_premium for b in biases]
        assert premiums == sorted(premiums, reverse=True)

    def test_total_contracts_count(self, contracts):
        biases = BiasEngine().compute(contracts)
        nvda   = next(b for b in biases if b.ticker == "NVDA")
        assert nvda.total_contracts == 2


# ── PersistenceTracker ─────────────────────────────────────────────────────────

class TestPersistenceTracker:

    def _bias(self, ticker, direction):
        b = TickerBias(ticker=ticker)
        b.call_volume = 1000 if direction == "Long" else 100
        b.put_volume  = 100  if direction == "Long" else 1000
        return b

    def test_first_day_is_one(self):
        with tempfile.TemporaryDirectory() as d:
            t = PersistenceTracker(Path(d))
            biases = [self._bias("NVDA", "Long")]
            t.annotate(biases)
            assert biases[0].consecutive_days == 1

    def test_second_day_same_direction_is_two(self):
        with tempfile.TemporaryDirectory() as d:
            t = PersistenceTracker(Path(d))
            t.annotate([self._bias("NVDA", "Long")])
            day2 = [self._bias("NVDA", "Long")]
            t.annotate(day2)
            assert day2[0].consecutive_days == 2

    def test_reversal_resets_to_one(self):
        with tempfile.TemporaryDirectory() as d:
            t = PersistenceTracker(Path(d))
            t.annotate([self._bias("NVDA", "Long")])
            day2 = [self._bias("NVDA", "Short")]
            t.annotate(day2)
            assert day2[0].consecutive_days == 1

    def test_three_day_streak(self):
        with tempfile.TemporaryDirectory() as d:
            t = PersistenceTracker(Path(d))
            for _ in range(3):
                biases = [self._bias("TSLA", "Short")]
                t.annotate(biases)
            assert biases[0].consecutive_days == 3


# ── Signal strength ────────────────────────────────────────────────────────────

class TestSignalStrength:

    def _bias(self, days, premium, parity):
        b = TickerBias(ticker="TEST")
        b.consecutive_days = days
        b.total_premium    = premium
        b.call_volume = int(parity * 1000)
        b.put_volume  = 1000
        return b

    def test_strong(self):
        assert self._bias(3, 1_500_000, 4.0).signal_strength == "Strong"

    def test_moderate_two_days(self):
        assert self._bias(2, 100_000, 3.0).signal_strength == "Moderate"

    def test_moderate_high_premium(self):
        assert self._bias(1, 750_000, 3.0).signal_strength == "Moderate"

    def test_weak(self):
        assert self._bias(1, 50_000, 2.0).signal_strength == "Weak"
