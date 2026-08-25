# Runbook - Region A Failure

Use this runbook for a confirmed Region A outage. The default command asks for
an operator confirmation; `--auto` is reserved for the local drill and CI.

| Step | Owner | Command | Success signal |
|---|---|---|---|
| 1. Confirm outage | On-call SRE | `python chaos/kill_region.py status` | A is not ready and B is alive. |
| 2. Announce incident | Incident commander | `python -c "import time; print(time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))"` | Timestamp and incident channel are recorded. |
| 3. Scale pool and fail over | On-call SRE | `python dr/runbook.py --primary a --target b --backend fs` | Step 3 reports `failover_ok: true`. |
| 4. Verify state replica | ML platform engineer | `curl http://127.0.0.1:8002/v1/state` | B reports weights true and count greater than zero. |
| 5. Verify DNS cutover | On-call SRE | `python -c "from pathlib import Path; print(Path('edge/active_region').read_text().strip())"` | Output is `b`; runbook step 5 has `cutover_ok: true`. |
| 6. Verify golden signals | On-call SRE | `python -c "import httpx; [print(httpx.get('http://127.0.0.1:8002/v1/infer').status_code) for _ in range(10)]"` | Ten 200 responses from B; compare with `reports/runbook-run.jsonl`. |
| 7. Post-incident summary | Incident commander | `python tools/measure_rto.py --loadgen reports/drill-2-withdr.jsonl --target-rto 300` | Output has `valid: true`, no warnings, and RTO PASS. |

## Rollback

If B lacks weights, has no vectors, returns a non-200 golden-signal response,
or the measurement is invalid, stop the cutover. The incident commander alone
may authorize a return to A, after A is healthy and state reconciliation is
complete. Restore a suspended A with
`python chaos/kill_region.py restore --region a --backend bare`; verify it
with `curl http://127.0.0.1:8001/readyz` before reversing DNS.

For a reproducible local exercise, run `python scripts/run_drill_2.py`. It
captures load, replication, health, failover, runbook, and chaos evidence.
