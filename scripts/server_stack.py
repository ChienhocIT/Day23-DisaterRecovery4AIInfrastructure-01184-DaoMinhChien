"""Background supervisor for the 3 uvicorn servers."""
import os
import pathlib
import subprocess
import sys
import time
import httpx

RUN_DIR = pathlib.Path("run")
RUN_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_DIR = pathlib.Path("reports")
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

# 1. Start Region A
env_a = os.environ.copy()
env_a.update({"REGION": "a", "STATE_DIR": "state/region-a", "WARMUP_SECONDS": "6"})
log_a = open(RUN_DIR / "region-a.log", "w", encoding="utf-8")
p_a = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "serving.app:app", "--host", "127.0.0.1", "--port", "8001", "--log-level", "warning"],
    env=env_a, stdout=log_a, stderr=subprocess.STDOUT
)
(RUN_DIR / "region-a.pid").write_text(str(p_a.pid))
print(f"region-a pid={p_a.pid} port=8001")

# 2. Start Region B
env_b = os.environ.copy()
env_b.update({"REGION": "b", "STATE_DIR": "state/region-b", "WARMUP_SECONDS": "6"})
log_b = open(RUN_DIR / "region-b.log", "w", encoding="utf-8")
p_b = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "serving.app:app", "--host", "127.0.0.1", "--port", "8002", "--log-level", "warning"],
    env=env_b, stdout=log_b, stderr=subprocess.STDOUT
)
(RUN_DIR / "region-b.pid").write_text(str(p_b.pid))
print(f"region-b pid={p_b.pid} port=8002")

# 3. Start Edge Proxy
env_edge = os.environ.copy()
env_edge.update({"EDGE_TTL_SECONDS": "5"})
log_edge = open(RUN_DIR / "edge.log", "w", encoding="utf-8")
p_edge = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "edge.proxy:app", "--host", "127.0.0.1", "--port", "8080", "--log-level", "warning"],
    env=env_edge, stdout=log_edge, stderr=subprocess.STDOUT
)
(RUN_DIR / "edge.pid").write_text(str(p_edge.pid))
print(f"edge pid={p_edge.pid} port=8080")

print("Services started, keeping supervisor alive...")
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    pass
finally:
    p_a.terminate()
    p_b.terminate()
    p_edge.terminate()
