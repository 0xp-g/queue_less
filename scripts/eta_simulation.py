"""Compare ETA strategies on a drifting workload (ADR-0007). Standard library only.

Two counters, a visitor every ~40 s, service time drifting from ~70 s to ~100 s halfway.
Uses the same EwmaEstimator/FixedEstimator classes as the API.

    python scripts/eta_simulation.py
"""

import heapq
import os
import random
import statistics
import sys
from collections import deque

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from app.domain.estimator import EtaEstimator, EwmaEstimator, FixedEstimator  # noqa: E402


def simulate(estimator: EtaEstimator, counters=2, n=600, seed=7, default=80.0):
    rng = random.Random(seed)
    arrivals, t = [], 0.0
    for _ in range(n):
        t += rng.expovariate(1 / 40)
        arrivals.append(t)
    switch = arrivals[n // 2]
    est = default
    events = [(a, 0, i, 0.0) for i, a in enumerate(arrivals)]
    heapq.heapify(events)
    q, busy, pred, act = deque(), 0, {}, {}
    while events:
        now, kind, i, dur = heapq.heappop(events)
        if kind == 0:  # arrival: predict with the current estimate, like the API at join time
            pred[i] = estimator.eta(len(q) + 1, est, counters, busy)
            q.append((i, now))
        else:  # a service finished: fold the observation in
            busy -= 1
            est = estimator.update(est, dur)
        while q and busy < counters:
            j, joined = q.popleft()
            act[j] = now - joined
            d = rng.lognormvariate(0, 0.3) * (70 if now < switch else 100)
            busy += 1
            heapq.heappush(events, (now + d, 1, j, d))
    return pred, act


def report(pred, act, min_wait=120):
    errs = [abs(pred[i] - act[i]) / act[i] for i in act if act[i] >= min_wait]
    return f"n={len(errs)} median={statistics.median(errs):.1%} mean={statistics.mean(errs):.1%}"


if __name__ == "__main__":
    print("fixed estimate :", report(*simulate(FixedEstimator())))
    for a in (0.1, 0.2, 0.3, 0.6):
        print(f"EWMA alpha={a}:", report(*simulate(EwmaEstimator(a))))
