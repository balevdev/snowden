"""Test Kelly criterion position sizing."""

from snowden.kelly import build_signal, compute_size, kelly_fraction
from snowden.types import Strategy


class TestKellyFraction:
    def test_no_edge_returns_none(self):
        assert kelly_fraction(0.50, 0.50) is None

    def test_small_edge_below_threshold(self):
        assert kelly_fraction(0.52, 0.50) is None

    def test_yes_side_basic(self):
        frac = kelly_fraction(0.70, 0.50, divisor=1.0)
        assert frac is not None
        assert 0.0 < frac <= 0.25

    def test_no_side_basic(self):
        frac = kelly_fraction(0.30, 0.50, divisor=1.0)
        assert frac is not None
        assert frac > 0

    def test_max_frac_clamp(self):
        frac = kelly_fraction(0.99, 0.50, divisor=1.0, max_frac=0.25)
        assert frac is not None
        assert frac <= 0.25

    def test_quarter_kelly(self):
        # Use max_frac=1.0 to avoid clamping affecting the comparison
        raw = kelly_fraction(0.80, 0.50, divisor=1.0, max_frac=1.0)
        quarter = kelly_fraction(0.80, 0.50, divisor=4.0, max_frac=1.0)
        assert quarter is not None and raw is not None
        assert abs(quarter - raw / 4) < 0.001

    def test_negative_edge_returns_none(self):
        # p_est < p_market but not enough edge
        assert kelly_fraction(0.48, 0.50) is None

    def test_extreme_confidence(self):
        frac = kelly_fraction(0.95, 0.50, divisor=1.0)
        assert frac is not None
        assert frac > 0


class TestComputeSize:
    def test_basic_size(self):
        size = compute_size(0.70, 0.50, bankroll=2000.0, divisor=1.0)
        assert size is not None
        assert size > 0

    def test_no_edge_returns_none(self):
        assert compute_size(0.50, 0.50, bankroll=2000.0) is None

    def test_below_min_usd(self):
        size = compute_size(0.54, 0.50, bankroll=100.0, divisor=4.0)
        # With very small bankroll and quarter kelly, might be below min
        if size is not None:
            assert size >= 5.0


class TestBuildSignal:
    def test_builds_yes_signal(self):
        signal = build_signal(
            market_id="m1",
            yes_token="yt1",
            no_token="nt1",
            p_est=0.75,
            p_market=0.50,
            confidence=0.9,
            bankroll=2000.0,
            strategy=Strategy.PARTISAN_FADE,
        )
        assert signal is not None
        assert signal.direction == "YES"
        assert signal.token_id == "yt1"
        assert signal.size_usd > 0

    def test_builds_no_signal(self):
        signal = build_signal(
            market_id="m1",
            yes_token="yt1",
            no_token="nt1",
            p_est=0.25,
            p_market=0.50,
            confidence=0.9,
            bankroll=2000.0,
            strategy=Strategy.LONGSHOT_FADE,
        )
        assert signal is not None
        assert signal.direction == "NO"
        assert signal.token_id == "nt1"

    def test_no_signal_below_threshold(self):
        signal = build_signal(
            market_id="m1",
            yes_token="yt1",
            no_token="nt1",
            p_est=0.52,
            p_market=0.50,
            confidence=0.5,
            bankroll=2000.0,
            strategy=Strategy.THETA,
        )
        assert signal is None
