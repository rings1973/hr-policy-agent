"""Measure cold-start and warm latency of a deployed app.

    python -m evaluation.latency_probe https://<app>.onrender.com --rounds 3 --idle-minutes 16

Render's free tier spins an instance down after 15 minutes without traffic. Each round waits
--idle-minutes, then times the first /health (the cold start) and the /chat right after it, then
a few warm /health calls. Results go to evaluation/results/<UTC>_latency.json.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from evaluation.metrics import percentile
from evaluation.run_eval import RESULTS_DIR

QUESTION = "How many PTO days do full-time employees get per year?"


def timed(client: httpx.Client, method: str, url: str, **kw: Any) -> dict[str, Any]:
    t0 = time.perf_counter()
    try:
        r = client.request(method, url, **kw)
        status = r.status_code
    except httpx.HTTPError as exc:
        status = f"{type(exc).__name__}"
    return {"status": status, "ms": int((time.perf_counter() - t0) * 1000)}


def run(base: str, rounds: int, idle_minutes: float, warm: int) -> dict[str, Any]:
    base = base.rstrip("/")
    out: dict[str, Any] = {"kind": "latency", "target": base, "idle_minutes": idle_minutes,
                           "started_at": datetime.now(UTC).isoformat(timespec="seconds"),
                           "rounds": []}
    with httpx.Client(timeout=300) as client:
        for i in range(rounds):
            if i or idle_minutes:
                print(f"round {i + 1}: idling {idle_minutes} min", flush=True)
                time.sleep(idle_minutes * 60)
            cold = timed(client, "GET", f"{base}/health")
            chat = timed(client, "POST", f"{base}/chat", json={"message": QUESTION})
            warm_ms = [timed(client, "GET", f"{base}/health")["ms"] for _ in range(warm)]
            row = {"cold_health": cold, "first_chat": chat, "warm_health_ms": warm_ms}
            print(json.dumps(row), flush=True)
            out["rounds"].append(row)
    colds = [r["cold_health"]["ms"] for r in out["rounds"]]
    warms = [ms for r in out["rounds"] for ms in r["warm_health_ms"]]
    out["summary"] = {"cold_health_ms_max": max(colds), "cold_health_ms_p50": percentile(colds, .5),
                      "warm_health_ms_p50": percentile(warms, .5),
                      "first_chat_ms": [r["first_chat"]["ms"] for r in out["rounds"]]}
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("url")
    p.add_argument("--rounds", type=int, default=3)
    p.add_argument("--idle-minutes", type=float, default=16)
    p.add_argument("--warm", type=int, default=5)
    args = p.parse_args(argv)
    result = run(args.url, args.rounds, args.idle_minutes, args.warm)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}_latency.json"
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result["summary"], indent=2), f"\nSaved {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
