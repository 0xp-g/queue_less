"""Wait-time estimation (ADR-0007) - Strategy pattern.

Estimators are stateless: the rolling estimate lives in queues.est_service_sec, so every API
instance shares it and an update happens under the queue row lock. A strategy only knows how to
fold one observation into the current estimate.
"""

from abc import ABC, abstractmethod

from app.core.config import Settings

MIN_OBSERVED_SEC = 1.0
MAX_OBSERVED_SEC = 3600.0


class EtaEstimator(ABC):
    @abstractmethod
    def update(self, current_estimate: float, observed_sec: float) -> float:
        """Return the new per-ticket service time estimate after one completed service."""

    def eta(
        self,
        position: int,
        service_sec: float,
        active_counters: int,
        busy_counters: int = 0,
    ) -> float:
        """Seconds until the ticket at `position` is called.

        ETA = (people_ahead + 1) * est / counters, refined for idle counters: if a counter
        is free and you are next in line for it, you are called immediately.
        """
        counters = max(1, active_counters)
        free = max(0, counters - busy_counters)
        if position <= free:
            return 0.0
        return round((position - free) * service_sec / counters, 1)

    @staticmethod
    def clamp(observed_sec: float) -> float:
        """Ignore absurd observations (clock skew, a ticket left open over lunch)."""
        return min(MAX_OBSERVED_SEC, max(MIN_OBSERVED_SEC, observed_sec))


class EwmaEstimator(EtaEstimator):
    """est <- alpha * observed + (1 - alpha) * est. Small alpha is smooth, large alpha reacts."""

    def __init__(self, alpha: float = 0.2):
        if not 0 < alpha <= 1:
            raise ValueError("alpha must be in (0, 1]")
        self.alpha = alpha

    def update(self, current_estimate: float, observed_sec: float) -> float:
        observed = self.clamp(observed_sec)
        return self.alpha * observed + (1 - self.alpha) * current_estimate


class FixedEstimator(EtaEstimator):
    """Baseline: never learns. Used to show what the EWMA buys us."""

    def update(self, current_estimate: float, observed_sec: float) -> float:
        return current_estimate


def build_estimator(settings: Settings) -> EtaEstimator:
    """Factory: pick the strategy from configuration."""
    if settings.eta_strategy == "fixed":
        return FixedEstimator()
    if settings.eta_strategy == "ewma":
        return EwmaEstimator(settings.eta_alpha)
    raise ValueError(f"unknown eta_strategy {settings.eta_strategy!r}")
