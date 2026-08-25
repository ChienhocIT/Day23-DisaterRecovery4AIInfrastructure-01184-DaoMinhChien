"""BƯỚC 3b — SINH VIÊN VIẾT. Cutover sang region phụ.

5 bước, THỨ TỰ QUAN TRỌNG (§2 Kiến Trúc Tham Chiếu: DNS/LB, compute, state là 3 lớp riêng):
  1_verify_target    — /v1/state của region phụ: weights? vector count? pool_state?
  2_restore_snapshot — gọi state/snapshot.py get + state/snapshot.py rpo()
                       Log BẮT BUỘC: rpo_seconds, docs_lost, embed_model_version.
                       (§3: "backup index nhưng quên backup embedding model version
                        -> index không tương thích khi restore")
  3_scale_pool       — ghi "full" vào state/region-<t>/pool_state (warm -> full)
  4_wait_ready       — POLL /readyz tới khi 200. Region phụ có WARMUP_SECONDS —
                       đây là GPU pool warm-up của §4, nó nằm trong RTO của bạn.
  5_dns_cutover      — ghi region đích vào edge/active_region

BẪY: nếu bạn đổi edge/active_region TRƯỚC bước 4, user sẽ nhận 503 từ CẢ HAI region
và RTO của bạn dài hơn, không ngắn hơn. Nếu bước 4 timeout -> ABORT, KHÔNG cutover.

Mỗi bước ghi 1 dòng vào reports/failover-events.jsonl với ts + step.
Không có dòng 5_dns_cutover = tools/measure_rto.py không tìm được t_cutover = mất điểm.

Chạy:  python dr/failover.py --target b --backend fs
"""
import argparse
import json
import pathlib
import sys
import time

import httpx

sys.path.insert(0, ".")
from state import snapshot  # noqa: E402

URL = {"a": "http://127.0.0.1:8001", "b": "http://127.0.0.1:8002"}
LOG = pathlib.Path("reports/failover-events.jsonl")


def emit(**kw) -> dict:
    """Append 1 dòng JSONL có ts + iso vào LOG, và print ra stdout."""
    LOG.parent.mkdir(parents=True, exist_ok=True)
    t = time.time()
    rec = {
        "ts": t,
        "iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)),
        **kw,
    }
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
    print("FAILOVER", json.dumps(rec))
    return rec


def state_of(region: str) -> dict:
    """Lấy thông tin trạng thái hiện tại của region từ /v1/state."""
    base_url = URL.get(region, "http://127.0.0.1:8001" if region == "a" else "http://127.0.0.1:8002")
    try:
        r = httpx.get(f"{base_url}/v1/state", timeout=2.0)
        return r.json()
    except Exception as e:
        return {"region": region, "error": str(e)}


def failover(target: str, backend: str, wait: float = 60.0) -> dict:
    """5 bước failover đúng thứ tự:
    1_verify_target -> 2_restore_snapshot -> 3_scale_pool -> 4_wait_ready -> 5_dns_cutover
    """
    primary = "b" if target == "a" else "a"

    # Bước 1: 1_verify_target
    target_state = state_of(target)
    emit(step="1_verify_target", target=target, backend=backend, state=target_state)

    # Bước 2: 2_restore_snapshot
    meta = snapshot.get(target, backend)
    primary_db = pathlib.Path(f"state/region-{primary}/vectors.sqlite")
    target_db = pathlib.Path(f"state/region-{target}/vectors.sqlite")
    rpo_info = snapshot.rpo(primary_db, target_db)
    rpo_s = rpo_info.get("rpo_seconds")
    docs_lost = rpo_info.get("docs_lost")
    embed_ver = meta.get("embed_model_version")
    emit(
        step="2_restore_snapshot",
        target=target,
        backend=backend,
        rpo_seconds=rpo_s,
        docs_lost=docs_lost,
        embed_model_version=embed_ver,
        snapshot_meta=meta,
    )

    # Bước 3: 3_scale_pool
    pool_file = pathlib.Path(f"state/region-{target}/pool_state")
    pool_file.parent.mkdir(parents=True, exist_ok=True)
    pool_file.write_text("full\n")
    emit(step="3_scale_pool", target=target, pool_state="full")

    # Bước 4: 4_wait_ready
    base_url = URL.get(target, "http://127.0.0.1:8001" if target == "a" else "http://127.0.0.1:8002")
    ready_url = f"{base_url}/readyz"
    t_wait_start = time.time()
    ready = False
    last_reason = ""
    while time.time() - t_wait_start < wait:
        try:
            r = httpx.get(ready_url, timeout=1.5)
            if r.status_code == 200:
                ready = True
                break
            else:
                try:
                    last_reason = ",".join(r.json().get("reasons", []))
                except Exception:
                    last_reason = f"status_{r.status_code}"
        except Exception as e:
            last_reason = type(e).__name__
        time.sleep(0.3)

    waited_s = round(time.time() - t_wait_start, 2)
    if not ready:
        emit(
            step="4_wait_ready",
            target=target,
            ready=False,
            waited_s=waited_s,
            error="timeout",
            reason=last_reason,
        )
        return {
            "ok": False,
            "step": "4_wait_ready",
            "target": target,
            "error": "target_not_ready_timeout",
            "waited_s": waited_s,
            "rpo_seconds": rpo_s,
            "docs_lost": docs_lost,
            "embed_model_version": embed_ver,
        }

    emit(step="4_wait_ready", target=target, ready=True, waited_s=waited_s)

    # Bước 5: 5_dns_cutover
    active_file = pathlib.Path("edge/active_region")
    active_file.parent.mkdir(parents=True, exist_ok=True)
    active_file.write_text(f"{target}\n")
    emit(step="5_dns_cutover", target=target, active_region=target)

    # Lấy vector stats sau khi restore
    stats = state_of(target)
    return {
        "ok": True,
        "target": target,
        "active_region": target,
        "rpo_seconds": rpo_s,
        "docs_lost": docs_lost,
        "embed_model_version": embed_ver,
        "waited_s": waited_s,
        "count": stats.get("count", 0),
        "weights": stats.get("weights", True),
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--target", default="b", choices=["a", "b"])
    p.add_argument("--backend", default="fs", choices=["fs", "minio"])
    p.add_argument("--wait", type=float, default=60)
    a = p.parse_args()
    print(json.dumps(failover(a.target, a.backend, a.wait), indent=2))
