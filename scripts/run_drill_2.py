"""Run the complete DR drill with reproducible, timestamped evidence.

This is the cross-platform counterpart to ``run_drill_1.py``.  It deliberately
waits for the health-check threshold before invoking the runbook so the
resulting RTO measures the automation path rather than a manual early cutover.
"""
import json
import pathlib
import subprocess
import sys
import time

import httpx


ROOT = pathlib.Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"


def command(*parts: str) -> list[str]:
    return [sys.executable, *parts]


def run() -> int:
    REPORTS.mkdir(exist_ok=True)
    for name in ("drill-2-withdr.jsonl", "health-events.jsonl", "failover-events.jsonl",
                 "runbook-run.jsonl", "replication.jsonl"):
        (REPORTS / name).unlink(missing_ok=True)
    (ROOT / "edge" / "active_region").write_text("a\n", encoding="ascii")
    # Tests and previous drills may leave B at full capacity.  Reset the
    # standby pool so this drill includes the required warm-up interval.
    (ROOT / "state" / "region-b" / "pool_state").write_text("warm\n", encoding="ascii")
    for _ in range(10):
        try:
            standby = httpx.get("http://127.0.0.1:8002/readyz", timeout=1.0).json()
            if standby.get("pool_state") == "warm":
                break
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    else:
        raise RuntimeError("Region B did not enter warm standby state")

    # Replication starts before the outage.  A 10-second interval gives this
    # short local drill a measurable (rather than assumed) RPO.
    ingest = subprocess.Popen(command("state/ingest.py", "--region", "a", "--rate", "1",
                                      "--duration", "45"), cwd=ROOT)
    replicate = subprocess.Popen(command("state/replicate.py", "--every", "10", "--duration",
                                         "45", "--backend", "fs"), cwd=ROOT)
    time.sleep(2)

    loadgen = subprocess.Popen(command("loadgen/traffic.py", "--duration", "40", "--rps", "2",
                                       "--out", "reports/drill-2-withdr.jsonl"), cwd=ROOT)
    health = subprocess.Popen(command("dr/health_checker.py", "--interval", "2", "--threshold",
                                      "3", "--duration", "40", "--out",
                                      "reports/health-events.jsonl"), cwd=ROOT)
    try:
        # Start just after a poll boundary: the full threshold is observable in
        # the log and still leaves enough traffic after cutover to measure RTO.
        time.sleep(9.5)
        subprocess.run(command("chaos/kill_region.py", "--region", "a", "--mode", "netblock",
                               "--mock"), cwd=ROOT, check=True)
        time.sleep(7)
        runbook = subprocess.run(command("dr/runbook.py", "--primary", "a", "--target", "b",
                                         "--backend", "fs", "--auto"), cwd=ROOT, check=True,
                                 capture_output=True, text=True)
        print(runbook.stdout)
        result = json.loads(runbook.stdout[runbook.stdout.rfind("{"):])
        if not result.get("ok"):
            raise RuntimeError(f"runbook failed: {result}")
        loadgen.wait()
        return 0
    finally:
        for proc in (ingest, replicate, health):
            proc.wait()
        subprocess.run(command("chaos/kill_region.py", "restore", "--region", "a", "--backend",
                               "bare"), cwd=ROOT, check=False)


if __name__ == "__main__":
    raise SystemExit(run())
