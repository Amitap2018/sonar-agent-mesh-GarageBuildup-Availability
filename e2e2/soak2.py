"""Post-deploy soak. Judges only what a short load test can see: error rate against the SLO, and hard exceptions.
It does NOT judge latency, memory growth or the correctness of values: those are the failures it can miss."""
import json, sys, threading, time, concurrent.futures as cf
sys.path.insert(0, "."); sys.path.insert(0, "e2e2")
from service import priced

SLO_ERR_PCT, CONCURRENCY, REQUESTS = 2.0, 40, 400
_leak = []

def run(cfg):
    pool = threading.BoundedSemaphore(cfg["pool_size"]); lock = threading.Lock()
    st = {"pool_errors": 0, "downstream_errors": 0, "exceptions": 0}
    def one(i):
        if not pool.acquire(timeout=0.05):
            with lock: st["pool_errors"] += 1
            return
        try:
            time.sleep((cfg["request_ms"] + cfg.get("extra_latency_ms", 0)) / 1000)
            if cfg.get("leak_kb", 0): _leak.append(bytearray(int(cfg["leak_kb"] * 1024)))
            if ((i * 2654435761) % 1000) / 10.0 < cfg.get("downstream_error_pct", 0):
                with lock: st["downstream_errors"] += 1
                return
            try: priced(10 + i % 500, ("debit", "credit", "amex")[i % 3], i % 4 == 0, cfg)
            except Exception:
                with lock: st["exceptions"] += 1
        finally: pool.release()
    with cf.ThreadPoolExecutor(CONCURRENCY) as ex: list(ex.map(one, range(REQUESTS)))
    err = 100.0 * (st["pool_errors"] + st["downstream_errors"]) / REQUESTS
    st.update({"error_rate_pct": round(err, 2), "slo_pct": SLO_ERR_PCT, "requests": REQUESTS, "leak_kb_total": int(len(_leak) * cfg.get("leak_kb", 0))})
    return st

if __name__ == "__main__":
    st = run(json.load(open("e2e2/service.json"))); print(json.dumps(st))
    sys.exit(1 if st["exceptions"] or st["error_rate_pct"] > SLO_ERR_PCT else 0)
