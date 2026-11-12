"""QueueLess load test: concurrent participants, live-update latency (p95) and ETA error.
From the defence kit, Part 9.7.

    pip install websockets   # enables WebSocket mode (otherwise polling mode is used)
    python scripts/queueless_load.py --api http://localhost:8000 --queue 1 --join-token <qr-token> \
        --staff-token <JWT> --participants 100 --rounds 3 --counters 2 --service-mean 2.0

Measures
  * update latency: time from a staff 'call next' response to each connected participant
    observing the new now-serving number (WebSocket push, or polling with --poll)
  * ETA error: ETA shown at join vs actual wait until the ticket was called
  * events generated: joins + calls + completions (target 1,000+)
"""

import argparse
import asyncio
import concurrent.futures as cf
import json
import random
import statistics
import threading
import time
import uuid

from common import http, pick, summary, write_report

ROUTES = {
    "join": "/api/queues/{q}/tickets",
    "status": "/api/tickets/{t}",
    "call": "/api/queues/{q}/call-next",
    "complete": "/api/tickets/{tid}/complete",
    "ws": "/ws/queues/{q}?ticket={t}",
}


class Observer:
    """Records, per participant, the first time each now-serving value is seen."""

    def __init__(self):
        self.lock = threading.Lock()
        self.seen = {}

    def saw(self, who, serving):
        now = time.time()
        with self.lock:
            d = self.seen.setdefault(who, {})
            for s in range(int(serving), -1, -1):  # seeing 37 implies 36 was passed
                if s in d:
                    break
                d[s] = now


def poll_loop(api, token, who, obs, stop, interval):
    while not stop.is_set():
        st, d, _ = http("GET", api + ROUTES["status"].format(t=token), timeout=10)
        if st == 200 and pick(d, "now_serving") is not None:
            obs.saw(who, pick(d, "now_serving"))
        stop.wait(interval)


async def ws_listen(url, who, obs, stop):
    import websockets

    async with websockets.connect(url) as ws:
        while not stop.is_set():
            try:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=1.0))
            except asyncio.TimeoutError:
                continue
            if pick(msg, "now_serving") is not None:
                obs.saw(who, pick(msg, "now_serving"))


def run(a):
    staff = {"Authorization": f"Bearer {a.staff_token}"} if a.staff_token else {}
    obs, stop, rng = Observer(), threading.Event(), random.Random(a.seed)
    tickets, call_log, events, errors = [], [], 0, 0
    try:
        import websockets  # noqa: F401

        mode = "websocket" if not a.force_polling else "polling"
    except ImportError:
        mode = "polling"

    def join(i):
        body = {"join_token": a.join_token, "client_request_id": str(uuid.uuid4())}
        st, d, el = http("POST", a.api + ROUTES["join"].format(q=a.queue), body)
        return {
            "who": i,
            "http": st,
            "latency": el,
            "joined": time.time(),
            "token": pick(d, "token", "ticket_token"),
            "id": pick(d, "id", "ticket_id"),
            "seq": pick(d, "seq"),
            "eta": pick(d, "eta_seconds", "eta"),
        }

    listeners = []
    for rnd in range(a.rounds):
        with cf.ThreadPoolExecutor(max_workers=min(a.participants, 64)) as ex:  # simultaneous
            batch = list(ex.map(join, range(rnd * a.participants, (rnd + 1) * a.participants)))
        good = [t for t in batch if t["http"] in (200, 201) and t["token"]]
        errors += len(batch) - len(good)
        events += len(good)
        tickets += good
        for t in good:  # one listener per ticket
            if mode == "websocket":
                url = a.api.replace("http", "ws", 1) + ROUTES["ws"].format(q=a.queue, t=t["token"])
                th = threading.Thread(
                    target=lambda u=url, w=t["who"]: asyncio.run(ws_listen(u, w, obs, stop)),
                    daemon=True,
                )
            else:
                th = threading.Thread(
                    target=poll_loop,
                    args=(a.api, t["token"], t["who"], obs, stop, a.poll),
                    daemon=True,
                )
            th.start()
            listeners.append(th)
        time.sleep(1.0)  # let connections settle
        remaining = len(good)
        while remaining > 0:  # staff serve the round
            for _ in range(min(a.counters, remaining)):
                st, d, _ = http("POST", a.api + ROUTES["call"].format(q=a.queue), {}, staff)
                if st not in (200, 201):
                    errors += 1
                    remaining = 0
                    break
                call_log.append({"t": time.time(), "seq": pick(d, "seq"), "id": pick(d, "id")})
                events += 1
                remaining -= 1
            time.sleep(max(0.05, rng.expovariate(1 / a.service_mean)))  # simulated service
            for c in call_log[-a.counters :]:
                if c.get("done"):
                    continue
                st, _, _ = http("POST", a.api + ROUTES["complete"].format(tid=c["id"]), {}, staff)
                c["done"] = True
                events += st in (200, 201, 204)
    time.sleep(a.poll * 2 + 1)
    stop.set()

    # update latency: every participant still waiting at call time should observe the call
    by_seq = {t["seq"]: t for t in tickets}
    latencies, missed = [], 0
    for c in call_log:
        for t in tickets:
            if t["seq"] is None or c["seq"] is None or t["seq"] < c["seq"] or t["joined"] > c["t"]:
                continue
            seen = obs.seen.get(t["who"], {}).get(c["seq"])
            if seen is None:
                missed += 1
            else:
                latencies.append(max(0.0, seen - c["t"]))
    # ETA error: ETA at join vs actual wait until called
    errs = []
    for c in call_log:
        t = by_seq.get(c["seq"])
        if t and t["eta"] is not None:
            actual = c["t"] - t["joined"]
            if actual >= a.min_wait:
                errs.append(abs(float(t["eta"]) - actual) / actual)
    lines = [
        "# QueueLess load test",
        f"mode: {mode}" + (f" (poll interval {a.poll}s)" if mode == "polling" else ""),
        f"participants per round: {a.participants} rounds: {a.rounds} counters: {a.counters}",
        f"tickets: {len(tickets)} calls: {len(call_log)} events generated: {events} "
        f"errors: {errors}",
        summary("join latency", [t["latency"] for t in tickets]),
        summary("update latency (staff action -> participant sees it)", latencies),
        f"updates expected but never observed: {missed}",
        (
            f"ETA error (waits >= {a.min_wait}s): n={len(errs)} "
            f"median={statistics.median(errs):.1%} mean={statistics.mean(errs):.1%}"
        )
        if errs
        else "ETA error: no eligible samples (server returned no ETA?)",
    ]
    write_report(a.report, lines)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--api", default="http://localhost:8000")
    p.add_argument("--queue", required=True)
    p.add_argument("--join-token", default="")
    p.add_argument("--staff-token", default="")
    p.add_argument("--participants", type=int, default=100)
    p.add_argument("--rounds", type=int, default=3)
    p.add_argument("--counters", type=int, default=2)
    p.add_argument("--service-mean", type=float, default=2.0)
    p.add_argument("--poll", type=float, default=0.25)
    p.add_argument("--min-wait", type=float, default=5.0)
    p.add_argument("--force-polling", action="store_true")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--report", default="queueless_load_report.md")
    run(p.parse_args())
