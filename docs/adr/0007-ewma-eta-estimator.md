# ADR-0007: EWMA service-time estimator behind a Strategy interface

**Status:** Accepted

## Context
A fixed "80 s per person" ETA drifts badly when service speed changes (a slow clerk, complex cases after lunch). We need an estimate that adapts but isn't jumpy, and a way to *measure* accuracy.

## Decision
* `ETA = (people_ahead + 1) × est ÷ max(1, active_counters)`.
* `est ← α·observed + (1−α)·est` per completed service. α defaults to 0.2 and is configurable per deployment. The cold start uses the queue's `default_service_sec`.
* `EtaEstimator` is an ABC with `EwmaEstimator` and `FixedEstimator` implementations (Strategy pattern), chosen by `build_estimator(settings)`.
* We store `eta_at_join_sec` on each ticket. After it's called we compute `|eta − actual| / actual`, excluding waits under 5 s because percentage error explodes near zero, and report the median and mean.

## Alternatives rejected
* **Simple moving average of the last N:** needs a stored window; EWMA needs one float.
* **ML model:** no training data at MVP; out of scope.

## Consequences
* `scripts/eta_simulation.py` compares strategies and α values on a drifting workload (in the kit's simulation, EWMA roughly halves the error of a fixed estimate).
* Known blind spots, stated honestly: no-shows ahead of you (they make waits shorter than predicted) and counters opening or closing mid-wait.
