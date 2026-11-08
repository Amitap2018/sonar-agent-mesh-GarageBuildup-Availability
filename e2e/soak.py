"""Post-deploy soak: replays a production-like concurrent traffic mix against the payments code
using the service's runtime config. Exits 1 if the error rate breaches the SLO."""
import json, sys, threading, time, concurrent.futures as cf
sys.path.insert(0, ".")
from payments.fees import card_fee

SLO_ERR_PCT = 2.0
CONCURRENCY = 40
REQUESTS = 400

def main(cfg_path="e2e/service.json"):
    cfg = json.load(open(cfg_path))
    pool = threading.BoundedSemaphore(cfg["pool_size"])
    errors = 0; lock = threading.Lock()
    def one(i):
        nonlocal errors
        if not pool.acquire(timeout=0.05):          # connection pool exhausted
            with lock: errors += 1
            return
        try:
            time.sleep(cfg["request_ms"] / 1000)
            card_fee(10 + i % 500, ("debit", "credit", "amex")[i % 3], i % 4 == 0)
        finally:
            pool.release()
    with cf.ThreadPoolExecutor(CONCURRENCY) as ex: list(ex.map(one, range(REQUESTS)))
    rate = 100.0 * errors / REQUESTS
    print(json.dumps({"pool_size": cfg["pool_size"], "requests": REQUESTS, "errors": errors, "error_rate_pct": round(rate, 2), "slo_pct": SLO_ERR_PCT}))
    return 0 if rate <= SLO_ERR_PCT else 1

if __name__ == "__main__": sys.exit(main())
