"""Script to execute Drill 1 (Baseline No-DR)."""
import subprocess
import sys
import time
import pathlib
import json

# Ensure reports directory exists
pathlib.Path("reports").mkdir(parents=True, exist_ok=True)
pathlib.Path("chaos").mkdir(parents=True, exist_ok=True)

# 1. Start traffic generator in background
out_file = "reports/drill-1-nodr.jsonl"
if pathlib.Path(out_file).exists():
    pathlib.Path(out_file).unlink()

print("Starting traffic generator for 40s (2 RPS)...")
loadgen_proc = subprocess.Popen([
    sys.executable, "loadgen/traffic.py", "--duration", "40", "--rps", "2", "--out", out_file
])

# 2. Wait 8 seconds
print("Waiting 8 seconds before chaos kill...")
time.sleep(8)

# 3. Kill Region A
print("Killing Region A...")
subprocess.run([
    sys.executable, "chaos/kill_region.py", "--region", "a", "--mode", "netblock", "--mock"
], check=True)

# 4. Wait for traffic generator to complete
loadgen_proc.wait()
print("Traffic generator finished.")

# 5. Measure RTO
print("Measuring RTO for Drill 1...")
res = subprocess.run([
    sys.executable, "tools/measure_rto.py", "--loadgen", out_file, "--target-rto", "300"
], capture_output=True, text=True)
print(res.stdout)

# Save measurement
pathlib.Path("reports/measure-drill-1.json").write_text(res.stdout, encoding="utf-8")

# 6. Restore Region A
print("Restoring Region A...")
subprocess.run([
    sys.executable, "chaos/kill_region.py", "restore", "--region", "a", "--backend", "bare"
], check=True)

print("Drill 1 complete!")
