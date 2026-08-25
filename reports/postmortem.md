# Postmortem - Region A DR Drill

## Summary

Region A was suspended with the local netblock chaos mode while users sent
traffic through the edge proxy. The baseline without DR did not recover and
recorded 12 failed requests. The DR drill detected the outage, restored Region
B, warmed its pool, cut DNS, and recovered traffic on B.

## Impact and timeline

- Outage started at `chaos/chaos-events.jsonl:3`.
- First user failure was 0.0s after outage in `reports/drill-2-withdr.jsonl:21`.
- Health detection was 9.6s after outage in `reports/health-events.jsonl:2`.
- DNS cutover was 17.2s after outage in `reports/failover-events.jsonl:5`.
- First successful B request was 22.1s after outage in `reports/drill-2-withdr.jsonl:30`.

Measured RTO: 22.1s, against a 300s target: PASS.
Measured RPO: 4.0s and 4 documents lost, recorded in
`reports/failover-events.jsonl:2`.

## Gap analysis

The main gap is the time between outage and detection: the configured 2.0s
interval and threshold 3 create a 6.0s minimum detection floor, while this
run observed 9.6s because of polling alignment and request timeouts. The next
largest gap is the 6.6s GPU warm-up in `reports/failover-events.jsonl:4`.
DNS cache convergence added about 4.9s after cutover.

An earlier Windows run exposed a reliability gap in the chaos helper: Unix
PID probing and SIGSTOP/SIGCONT are not portable. The helper now validates a
Windows PID and uses the Windows suspend/resume APIs, preventing a false kill
event from being used as evidence.

## Action items

1. Owner: platform engineer. Evaluate a shorter health interval only after
   confirming that the higher polling rate does not cause flapping.
2. Owner: ML serving engineer. Keep a smaller warm standby pool, or pre-warm
   B during elevated-risk windows, to reduce the 6.77s warm-up gap.
3. Owner: SRE. Run `python scripts/run_drill_2.py` after every change to the
   failover path and retain the resulting evidence logs.
4. Owner: incident commander. Keep error_rate 0.0 in the golden-signal check
   (`reports/runbook-run.jsonl:6`) as a follow-up alert even though RTO passed.
