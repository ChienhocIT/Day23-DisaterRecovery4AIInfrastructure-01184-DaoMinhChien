"""BƯỚC 3c — SINH VIÊN VIẾT. Tự động hoá runbook §4 "Runbook: Region Chính Down".

7 bước trên slide, mỗi bước 1 dòng log có ts. Log này CHÍNH LÀ timeline của postmortem.
  1 xac_nhan_outage          — probe cả 2 region, đừng tin 1 lần fail (dùng nhiều lần
                              hoặc gọi health_checker.probe nếu đã viết xong 3a)
  2 thong_bao_incident       — ts của dòng này là mốc "operator biết tin", LUÔN LUÔN
                              SAU t_outage trong chaos-events (không thể trùng — operator
                              không thể biết ngay giây outage xảy ra). Ghi cả 2 ts vào
                              log để postmortem tính được "độ trễ thông báo".
  3 scale_gpu_pool           — gọi HÀM `failover.failover(...)` MỘT LẦN DUY NHẤT. Hàm
                              đó tự làm đủ 5 bước con (verify/restore/scale/wait/cutover)
                              và tự ghi log riêng vào reports/failover-events.jsonl.
  4 verify_state_replica     — KHÔNG gọi lại failover — chỉ ĐỌC kết quả (vector count +
                              weights ở region phụ) từ dict mà bước 3 trả về, để log vào
                              runbook-run.jsonl cho postmortem đọc 1 chỗ duy nhất.
  5 dns_cutover              — cũng chỉ đọc lại: kết quả cutover có ok hay không.
  6 verify_golden_signals    — 10 request thật vào region phụ: p95 latency + error rate
  7 post_incident            — elapsed_s + lệnh đo RTO

BÁN TỰ ĐỘNG, KHÔNG FULL-AUTO (§4: "failover đầu tiên nên là bán tự động — alert +
1-click confirm — tránh flapping gây failover 2 chiều liên tục"). Mặc định phải hỏi
người vận hành confirm; --auto chỉ dùng trong CI/khi chấm điểm.

Chạy:  python dr/runbook.py --primary a --target b --backend fs
"""
import argparse
import json
import pathlib
import sys
import time

import httpx

sys.path.insert(0, ".")
from dr import failover as fo  # noqa: E402

LOG = pathlib.Path("reports/runbook-run.jsonl")
URL = {"a": "http://127.0.0.1:8001", "b": "http://127.0.0.1:8002"}


def step(n, name, **kw) -> dict:
    """Ghi 1 dòng {ts, iso, step, name, ...} vào LOG."""
    LOG.parent.mkdir(parents=True, exist_ok=True)
    t = time.time()
    rec = {
        "ts": t,
        "iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)),
        "step": n,
        "name": name,
        **kw,
    }
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
    print(f"RUNBOOK STEP {n} ({name}):", json.dumps(rec))
    return rec


def confirm(auto: bool, msg: str) -> bool:
    """auto=True -> True; ngược lại hỏi y/N."""
    if auto:
        return True
    try:
        ans = input(f"{msg} [y/N]: ").strip().lower()
        return ans == "y"
    except Exception:
        return False


def run(primary: str, target: str, backend: str, auto: bool) -> dict:
    """7 bước runbook theo đúng tài liệu §4."""
    t_start = time.time()

    # Bước 1: 1_xac_nhan_outage
    p_alive = False
    p_url = URL.get(primary, "http://127.0.0.1:8001" if primary == "a" else "http://127.0.0.1:8002")
    try:
        r = httpx.get(f"{p_url}/readyz", timeout=1.5)
        p_alive = (r.status_code == 200)
    except Exception:
        p_alive = False

    t_url = URL.get(target, "http://127.0.0.1:8001" if target == "a" else "http://127.0.0.1:8002")
    t_alive = False
    try:
        r = httpx.get(f"{t_url}/healthz", timeout=1.5)
        t_alive = (r.status_code == 200)
    except Exception:
        t_alive = False

    step(1, "xac_nhan_outage", primary=primary, target=target, primary_alive=p_alive, target_alive=t_alive)

    # Bước 2: 2_thong_bao_incident
    if not confirm(auto, f"Xác nhận thực hiện failover từ region {primary} sang region {target}?"):
        step(2, "thong_bao_incident", action="aborted_by_operator")
        return {"ok": False, "aborted": True}

    step(2, "thong_bao_incident", primary=primary, target=target, auto=auto, confirmed=True)

    # Bước 3: 3_scale_gpu_pool (gọi failover DUY NHẤT 1 lần)
    fo_res = fo.failover(target=target, backend=backend, wait=60.0)
    step(3, "scale_gpu_pool", target=target, failover_ok=fo_res.get("ok"))
    if not fo_res.get("ok"):
        return {"ok": False, "step": 3, "failover": fo_res}

    # Bước 4: 4_verify_state_replica
    step(
        4,
        "verify_state_replica",
        target=target,
        vector_count=fo_res.get("count"),
        weights=fo_res.get("weights"),
        rpo_seconds=fo_res.get("rpo_seconds"),
        docs_lost=fo_res.get("docs_lost"),
        embed_model_version=fo_res.get("embed_model_version"),
    )

    # Bước 5: 5_dns_cutover
    step(5, "dns_cutover", active_region=target, cutover_ok=fo_res.get("ok"))

    # Bước 6: 6_verify_golden_signals (10 requests thật trực tiếp tới target)
    latencies = []
    statuses = []
    target_infer_url = f"{t_url}/v1/infer"
    with httpx.Client(timeout=3.0) as client:
        for i in range(10):
            t0 = time.time()
            try:
                res = client.get(target_infer_url, params={"q": f"probe query {i}"})
                lat_ms = (time.time() - t0) * 1000.0
                latencies.append(lat_ms)
                statuses.append(res.status_code)
            except Exception:
                lat_ms = (time.time() - t0) * 1000.0
                latencies.append(lat_ms)
                statuses.append(503)
            time.sleep(0.05)

    p95_ms = sorted(latencies)[int(len(latencies) * 0.95)] if latencies else 0.0
    err_rate = (sum(1 for s in statuses if s != 200) / len(statuses)) if statuses else 1.0
    step(6, "verify_golden_signals", requests=len(latencies), p95_ms=round(p95_ms, 1), error_rate=err_rate)

    # Bước 7: 7_post_incident
    elapsed_s = round(time.time() - t_start, 2)
    step(
        7,
        "post_incident",
        elapsed_s=elapsed_s,
        measure_cmd="python tools/measure_rto.py --loadgen reports/drill-2-withdr.jsonl",
    )

    return {
        "ok": True,
        "primary": primary,
        "target": target,
        "elapsed_s": elapsed_s,
        "rpo_seconds": fo_res.get("rpo_seconds"),
        "docs_lost": fo_res.get("docs_lost"),
        "p95_ms": round(p95_ms, 1),
        "error_rate": err_rate,
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--primary", default="a")
    p.add_argument("--target", default="b")
    p.add_argument("--backend", default="fs", choices=["fs", "minio"])
    p.add_argument("--auto", action="store_true")
    a = p.parse_args()
    print(json.dumps(run(a.primary, a.target, a.backend, a.auto), indent=2))
