# RTO/RPO Evidence - Lab 23

## Result

The final DR drill passed the 300s RTO target. Measured RTO is **22.1s** and
measured RPO is **4.0s** with **4 documents lost**. These values are produced
from the raw timestamped logs, not estimated manually.

| Milestone from outage | Observed | Evidence |
|---|---:|---|
| Region A netblock begins | 0.0s | `chaos/chaos-events.jsonl:3` |
| First user error | 0.0s | `reports/drill-2-withdr.jsonl:21` |
| Health checker marks A unhealthy | 9.6s | `reports/health-events.jsonl:2` |
| Snapshot restored; RPO recorded | 10.6s | `reports/failover-events.jsonl:2` |
| Region B ready after pool warm-up | 17.2s | `reports/failover-events.jsonl:4` |
| DNS cutover to B | 17.2s | `reports/failover-events.jsonl:5` |
| First successful request from B | 22.1s | `reports/drill-2-withdr.jsonl:30` |

## RTO breakdown

| Component | Time | Method and evidence |
|---|---:|---|
| Health-check detection | 9.6s | Outage to A UNHEALTHY. Checker uses 2.0s interval and threshold 3 in `reports/health-events.jsonl:2`. |
| Runbook handoff and snapshot restore | 1.0s | Detection to restore record in `reports/failover-events.jsonl:2`. |
| GPU pool warm-up | 6.6s | `waited_s` for B in `reports/failover-events.jsonl:4`. |
| DNS/LB cache convergence | 4.9s | Cutover to first B success, from `reports/failover-events.jsonl:5` and `reports/drill-2-withdr.jsonl:30`. |
| Total measured RTO | 22.1s | `python tools/measure_rto.py --loadgen reports/drill-2-withdr.jsonl --target-rto 300` |

The component values sum to the measured total: 9.6s + 1.0s + 6.6s +
4.9s = 22.1s.

## RPO and baseline comparison

Replication ran every 10.0s; the last pre-restore snapshot is recorded in
`reports/replication.jsonl:3`. The restore step measured RPO as 4.0s and
4 lost documents in `reports/failover-events.jsonl:2`.

The no-DR baseline produced 12 failed requests and no recovery. Its first
failed request is `reports/drill-1-nodr.jsonl:18`; the raw baseline measurement
is `reports/measure-drill-1.json:1`.
