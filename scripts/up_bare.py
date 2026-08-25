"""Cross-platform launcher for bare mode on Windows and POSIX."""
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

flags = 0
if sys.platform == "win32":
    flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS

# 1. Start Region A
env_a = os.environ.copy()
env_a.update({"REGION": "a", "STATE_DIR": "state/region-a", "WARMUP_SECONDS": "6"})
log_a = open(RUN_DIR / "region-a.log", "w", encoding="utf-8")
p_a = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "serving.app:app", "--host", "127.0.0.1", "--port", "8001", "--log-level", "warning"],
    env=env_a, stdout=log_a, stderr=subprocess.STDOUT, creationflags=flags
)
(RUN_DIR / "region-a.pid").write_text(str(p_a.pid))
print(f"region-a pid={p_a.pid} port=8001")

# 2. Start Region B
env_b = os.environ.copy()
env_b.update({"REGION": "b", "STATE_DIR": "state/region-b", "WARMUP_SECONDS": "6"})
log_b = open(RUN_DIR / "region-b.log", "w", encoding="utf-8")
p_b = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "serving.app:app", "--host", "127.0.0.1", "--port", "8002", "--log-level", "warning"],
    env=env_b, stdout=log_b, stderr=subprocess.STDOUT, creationflags=flags
)
(RUN_DIR / "region-b.pid").write_text(str(p_b.pid))
print(f"region-b pid={p_b.pid} port=8002")

# 3. Start Edge Proxy
env_edge = os.environ.copy()
env_edge.update({"EDGE_TTL_SECONDS": "5"})
log_edge = open(RUN_DIR / "edge.log", "w", encoding="utf-8")
p_edge = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "edge.proxy:app", "--host", "127.0.0.1", "--port", "8080", "--log-level", "warning"],
    env=env_edge, stdout=log_edge, stderr=subprocess.STDOUT, creationflags=flags
)
(RUN_DIR / "edge.pid").write_text(str(p_edge.pid))
print(f"edge pid={p_edge.pid} port=8080")

print("Cho cac service khoi dong (toi da 10s)...")
services = [("region-a", 8001, "/healthz"), ("region-b", 8002, "/healthz"), ("edge", 8080, "/edge/state")]
all_up = True

for name, port, endpoint in services:
    up = False
    for _ in range(20):
        try:
            r = httpx.get(f"http://127.0.0.1:{port}{endpoint}", timeout=1.0)
            if r.status_code == 200:
                up = True
                break
        except Exception:
            pass
        time.sleep(0.5)
    if up:
        print(f"  {name} (port {port}): UP")
    else:
        print(f"  {name} (port {port}): KHONG PHAN HOI -- xem run/{name}.log")
        all_up = False

if not all_up:
    print("MOT SO SERVICE CHUA LEN -- doc log truoc khi chay drill")
    sys.exit(1)

try:
    edge_state = httpx.get("http://127.0.0.1:8080/edge/state", timeout=2.0).json()
    print("Edge state:", edge_state)
except Exception as e:
    print("Edge state error:", e)
