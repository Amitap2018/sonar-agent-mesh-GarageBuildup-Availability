"""Learned gate (written by the Remediation agent after PRB for the connection-pool regression):
the pool must cover the soak concurrency, or the release is blocked before deploy."""
import json, sys
sys.path.insert(0, "e2e"); import soak
cfg = json.load(open("e2e/service.json"))
if cfg["pool_size"] < soak.CONCURRENCY:
    print(f"BLOCK: pool_size {cfg['pool_size']} < concurrency {soak.CONCURRENCY}"); sys.exit(1)
print("pool_saturation ok")
