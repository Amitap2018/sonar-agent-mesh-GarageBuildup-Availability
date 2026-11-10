"""Remediation agent: after a fix release has held in production, write the gate that would have stopped the failure,
and commit it to main. Auto-approved by policy (decision: learned gates need no human approval for now)."""
import json, os, re, subprocess, sys, time

def sh(*a, check=True):
    p = subprocess.run(list(a), capture_output=True, text=True)
    if check and p.returncode: raise RuntimeError(f"{' '.join(a)}: {p.stderr[-200:]}")
    return p.stdout

msg = sh("git", "log", "-1", "--format=%B")
cls = (re.search(r"^Failure-Class:\s*(\w+)", msg, re.M) or [None, None])[1]
prb = (re.search(r"^Fixes-Problem:\s*(PRB\d+)", msg, re.M) or [None, None])[1]
if not (cls and prb): print("no failure class on this release: nothing to learn"); sys.exit(0)
sys.path.insert(0, "e2e2"); import gatelib
if cls not in gatelib.CHECKS: print(f"no check exists for class {cls}"); sys.exit(0)
for attempt in range(8):
    sh("git", "fetch", "-q", "origin", "main"); sh("git", "checkout", "-q", "-B", "learn", "origin/main")
    gate = f"e2e2/gates/learned_{cls}.py"
    if os.path.exists(gate): print(f"gate for {cls} already learned"); sys.exit(0)
    os.makedirs("e2e2/gates", exist_ok=True)
    open(gate, "w").write(f'"""Learned gate (Remediation agent, from {prb}). Auto-approved by policy."""\nimport sys\nsys.path.insert(0, "e2e2")\nimport gatelib\nsys.exit(gatelib.check("{cls}"))\n')
    L = json.load(open("e2e2/learnings.json")) if os.path.exists("e2e2/learnings.json") else []
    L.append({"class": cls, "problem": prb, "run": os.environ.get("GITHUB_RUN_ID"), "approved": "auto, by policy"}); json.dump(L, open("e2e2/learnings.json", "w"), indent=1)
    sh("git", "add", gate, "e2e2/learnings.json")
    sh("git", "-c", "user.name=Remediation agent", "-c", "user.email=agent@example.invalid", "commit", "-q", "-m", f"Remediation agent: learned gate for {cls} (from {prb}, auto-approved by policy)")
    if subprocess.run(["git", "push", "-q", "origin", "learn:main"], capture_output=True).returncode == 0:
        print(f"learned gate {cls} committed to main"); sys.exit(0)
    time.sleep(2 + attempt)
sys.exit("could not commit the learned gate")
