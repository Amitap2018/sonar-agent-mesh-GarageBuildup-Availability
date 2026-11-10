"""Checks the Remediation agent can turn into learned gates. Each one is the cheapest pre-deploy test for one failure class."""
import json, sys
sys.path.insert(0, "."); sys.path.insert(0, "e2e2")
from payments.fees import card_fee
from service import priced

CONCURRENCY = 40

def _cfg(): return json.load(open("e2e2/service.json"))

def pool(c):       return c["pool_size"] >= CONCURRENCY, f"pool_size {c['pool_size']} < concurrency {CONCURRENCY}"
def dependency(c): return c.get("downstream_error_pct", 0) <= 1, f"downstream_error_pct {c.get('downstream_error_pct')} > 1"
def latency(c):    return c["request_ms"] + c.get("extra_latency_ms", 0) <= 20, f"latency budget {c['request_ms'] + c.get('extra_latency_ms', 0)} ms > 20 ms"
def leak(c):       return c.get("leak_kb", 0) == 0, f"leak_kb {c.get('leak_kb')} > 0"
def exception(c):
    for a in range(10, 3000, 30):
        for t in ("debit", "credit", "amex"):
            for i in (False, True):
                try: card_fee(a, t, i)
                except Exception as e: return False, f"card_fee({a},{t},{i}) raised {e}"
    return True, ""
def silent(c):
    g = json.load(open("e2e2/golden.json"))
    for k, want in g.items():
        a, t, i = k.split("|")
        try: got = priced(int(a), t, i == "True", c)
        except Exception: continue  # a crash is the 'exception' class, not a silent wrong value
        if got != want: return False, f"fee for {k} is {got}, golden {want}"
    return True, ""

CHECKS = {"pool": pool, "dependency": dependency, "latency": latency, "leak": leak, "exception": exception, "silent": silent}

def check(cls):
    ok, why = CHECKS[cls](_cfg())
    print(("learned gate " + cls + " ok") if ok else f"BLOCK (learned gate {cls}): {why}")
    return 0 if ok else 1
