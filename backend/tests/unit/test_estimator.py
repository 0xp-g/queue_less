import pytest

from app.core.config import Settings
from app.domain.estimator import EwmaEstimator, FixedEstimator, build_estimator


def test_ewma_moves_toward_observation():
    est = EwmaEstimator(alpha=0.2)
    assert est.update(80, 100) == pytest.approx(84.0)
    assert est.update(80, 80) == pytest.approx(80.0)


def test_ewma_converges_after_drift():
    est, e = EwmaEstimator(alpha=0.3), 70.0
    for _ in range(50):
        e = est.update(e, 100)
    assert e == pytest.approx(100, abs=0.1)


def test_outliers_are_clamped():
    est = EwmaEstimator(alpha=1.0)
    assert est.update(80, 10**6) == 3600
    assert est.update(80, -5) == 1


def test_fixed_never_learns():
    assert FixedEstimator().update(80, 200) == 80


@pytest.mark.parametrize(
    ("position", "counters", "busy", "expected"),
    [
        (1, 1, 1, 80.0),  # one busy counter: wait for one service
        (3, 2, 2, 120.0),  # 3 * 80 / 2
        (1, 2, 1, 0.0),  # a counter is free and you are first: called immediately
        (2, 2, 1, 40.0),  # one free counter takes #1; you wait (2 - 1) * 80 / 2
        (5, 0, 0, 320.0),  # no active counter: treated as 1 (free); (5 - 1) * 80 / 1
    ],
)
def test_eta(position, counters, busy, expected):
    assert EwmaEstimator().eta(position, 80, counters, busy) == expected


def test_alpha_validation():
    with pytest.raises(ValueError):
        EwmaEstimator(alpha=0)


def test_factory_selects_strategy():
    assert isinstance(build_estimator(Settings(eta_strategy="fixed")), FixedEstimator)
    assert isinstance(build_estimator(Settings(eta_strategy="ewma")), EwmaEstimator)
    with pytest.raises(ValueError):
        build_estimator(Settings(eta_strategy="magic"))
