# Measured results

Run on 2026-11-12 with `scripts/queueless_load.py` (defence kit Part 9) against the Docker Compose stack: one API container, PostgreSQL 16 and Redis 7, on a 4-vCPU / 16 GB cloud VM. The load generator ran on the same machine.

Settings: 100 participants per round × 3 rounds, 2 counters, mean simulated service time 2 s, WebSocket mode. The queue's default service time was set to 2 s, matching the workload. The join rate limit was disabled because every simulated visitor shares one IP.

```
# QueueLess load test
mode: websocket
participants per round: 100 rounds: 3 counters: 2
tickets: 300 calls: 300 events generated: 900 errors: 0
join latency: n=300 min=0.052s p50=1.614s p95=3.077s max=3.547s mean=1.644s
update latency (staff action -> participant sees it): n=15150 min=0.000s p50=0.017s p95=0.080s max=0.254s mean=0.024s
updates expected but never observed: 0
ETA error (waits >= 5.0s): n=290 median=13.5% mean=15.8%
```

| Resume claim | Target | Measured |
|---|---|---|
| 100+ simultaneous participants | 100+ | **300 tickets** (3 rounds × 100 joining at once), 0 errors |
| Queue events | 1,000 | **900** (300 joins + 300 calls + 300 completions). Use `--rounds 4` for 1,000+ |
| p95 live-update latency | < 500 ms | **80 ms** (p50 17 ms, max 254 ms over 15,150 observed updates, 0 missed) |
| ETA prediction error | < 20 % | **13.5 % median**, 15.8 % mean (waits ≥ 5 s, n = 290) |

**What I'd say in an interview:** p95 update latency was 80 ms at 300 connected sockets on one instance, and median ETA error was 13.5 %.
Join latency is the weak spot: p95 was 3.1 s when 100 people joined in the same instant. Joins for one queue are serialized on the queue row lock (by design, so numbers stay unique), and 64 concurrent requests also compete for one API process's connection pool. A real venue never sees 100 joins in the same second.
Next steps would be to shorten the join transaction and run more API workers.

Concurrency correctness (`backend/tests/integration/test_concurrency.py`): 45 concurrent joins with 5 retries gave 40 tickets with 40 distinct numbers. Two counters × 20 concurrent call-next requests gave 40 distinct tickets and 0 double calls.

ETA strategy comparison (`scripts/eta_simulation.py`, simulated drift from 70 s to 100 s): fixed estimate 22.7 % median error; EWMA α = 0.1 6.0 %, α = 0.2 8.6 %, α = 0.3 11.5 %.
