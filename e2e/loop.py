#!/usr/bin/env python3
"""The Stable Release Loop, ServiceNow side. Called by the GitHub workflow, one mode per step.

Modes
  open-change   risk-score the release, open a change, walk it to Scheduled/Implement, obtain approval
  close-ok      soak passed: close the change as successful; if this release is a fix, close the loop
  close-fail    soak failed: close the change unsuccessful, open incident + problem + GIT case, link them

Identities (separation of duties, each is its own OAuth client in ServiceNow)
  pipeline user         creates and moves records
  release approval agent  the only identity that may auto-approve, and only below the risk threshold
High-risk changes are approved by a person in ServiceNow; the pipeline waits and never approves them.

Standard library only. Secrets come from the environment and are never printed."""
import json, os, re, subprocess, sys, time, urllib.parse, urllib.request, urllib.error, datetime

BASE = os.environ.get("SN_INSTANCE", "").rstrip("/")
API = os.environ.get("SN_SCRIPTED_API", "/api/2308742/stable_loop")
GROUP_NAME = os.environ.get("SN_ASSIGNMENT_GROUP", "Conditional Script Writer")
HUMAN_WAIT_MIN = int(os.environ.get("SN_HUMAN_WAIT_MIN", "30"))
RUN_URL = f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{os.environ.get('GITHUB_REPOSITORY', '')}/actions/runs/{os.environ.get('GITHUB_RUN_ID', '')}"
REPO = os.environ.get("GITHUB_REPOSITORY", "")
PERM_FIX = "Resolved – Permanent Fix Applied"
ORDER = ["-5", "-4", "-3", "-2", "-1", "0", "3"]
STATE_FILE = os.environ.get("LOOP_STATE", "loop_state.json")
_tokens = {}


def log(msg): print(msg, flush=True)
def out(k, v):
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f: f.write(f"{k}={v}\n")
    log(f"  output {k}={v}")


# ---------- policy: the Release approval agent's decision ----------
def risk_score(policy, changed_files):
    """Score from application tier, size of the change and whether it touches sensitive paths."""
    tier_pts = {"1": 60, "2": 30, "3": 10}[str(policy.get("tier", 2))]
    size_pts = min(30, 3 * len(changed_files))
    sens = policy.get("sensitive_paths", ["payments/"])
    sens_pts = 20 if any(f.startswith(tuple(sens)) for f in changed_files) else 0
    return tier_pts + size_pts + sens_pts

def decide(policy, score):
    """auto  = the approval agent may approve; human = a person must approve."""
    if str(policy.get("tier")) == "1" or score >= policy.get("high_risk_threshold", 70): return "human"
    return "auto"

def changed_files():
    try:
        base = subprocess.run(["git", "merge-base", "origin/main", "HEAD"], capture_output=True, text=True).stdout.strip() or "HEAD~1"
        return [l for l in subprocess.run(["git", "diff", "--name-only", base, "HEAD"], capture_output=True, text=True).stdout.splitlines() if l]
    except Exception: return []

def fix_trailer():
    msg = subprocess.run(["git", "log", "-1", "--format=%B"], capture_output=True, text=True).stdout
    m = re.search(r"^Fixes-Problem:\s*(PRB\d+)", msg, re.M)
    return m.group(1) if m else ""


# ---------- ServiceNow transport (OAuth client credentials) ----------
def token(who):
    if who in _tokens: return _tokens[who]
    pre = "SN_CLIENT" if who == "pipeline" else "SN_APPROVER_CLIENT"
    cid, sec = os.environ.get(f"{pre}_ID", ""), os.environ.get(f"{pre}_SECRET", "")
    if not (BASE and cid and sec): sys.exit(f"missing ServiceNow settings for the {who} identity (SN_INSTANCE, {pre}_ID, {pre}_SECRET)")
    body = urllib.parse.urlencode({"grant_type": "client_credentials", "client_id": cid, "client_secret": sec}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(BASE + "/oauth_token.do", data=body, headers={"Content-Type": "application/x-www-form-urlencoded"}), timeout=40) as r:
            _tokens[who] = json.loads(r.read())["access_token"]
    except urllib.error.HTTPError as e:
        sys.exit(f"OAuth token request for the {who} identity failed: HTTP {e.code} {e.read().decode()[:200]}")
    return _tokens[who]

def call(method, path, body=None, who="pipeline"):
    req = urllib.request.Request(BASE + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": "Bearer " + token(who), "Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r: return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        txt = e.read().decode()[:400]
        try: j = json.loads(txt); msg = j.get("error", txt) if isinstance(j.get("error"), str) else (j.get("error", {}).get("message", "") + " " + j.get("error", {}).get("detail", ""))
        except Exception: msg = txt
        return e.code, {"error": msg}
    except Exception as ex: return 0, {"error": str(ex)}

def val(v): return v.get("value") if isinstance(v, dict) else v
def clean(d): return {k: v for k, v in d.items() if v not in ("", None)}
def create(table, data):
    s, r = call("POST", f"/api/now/table/{table}?sysparm_exclude_reference_link=true", clean(data))
    if s != 201: sys.exit(f"create {table} failed: HTTP {s} {r.get('error')}")
    return r["result"]
def read(table, sid, fields):
    s, r = call("GET", f"/api/now/table/{table}/{sid}?sysparm_exclude_reference_link=true&sysparm_fields={','.join(fields)}")
    return r.get("result", {}) if s == 200 else {}
def patch(table, sid, data): return call("PATCH", f"/api/now/table/{table}/{sid}", clean(data))
def st(table, sid): return val(read(table, sid, ["state"]).get("state"))
def find(table, query, fields):
    s, r = call("GET", f"/api/now/table/{table}?sysparm_query={urllib.parse.quote(query)}&sysparm_fields={','.join(fields)}&sysparm_limit=1&sysparm_exclude_reference_link=true")
    return (r.get("result") or [{}])[0] if s == 200 else {}
def work_note(table, sid, text): patch(table, sid, {"work_notes": text})

def whoami():
    return find("sys_user", "user_name=" + os.environ.get("SN_PIPELINE_USER", "e2e.agent"), ["sys_id"]).get("sys_id", "")


# ---------- change lifecycle ----------
def nextstates(cid):
    s, r = call("GET", f"/api/sn_chg_rest/change/{cid}/nextstates"); return r.get("result", {}) if s == 200 else {}
def transition(cid, to):
    for grp in nextstates(cid).get("state_transitions", []):
        for t in grp:
            if t.get("to_state") == to: return t
    return None

def close_change_tasks(cid, me):
    s, r = call("GET", f"/api/now/table/change_task?sysparm_query=change_request={cid}^active=true&sysparm_fields=sys_id&sysparm_exclude_reference_link=true")
    for t in (r.get("result", []) if s == 200 else []):
        patch("change_task", t["sys_id"], {"state": "3", "assigned_to": me, "close_notes": "Completed by the release pipeline", "close_code": "successful"})

def request_approval(cid, mode, score, gates_note):
    """auto: the release approval agent approves its own approval row. human: wait for a person."""
    rows = call("GET", f"/api/now/table/sysapproval_approver?sysparm_query=sysapproval={cid}^state=requested&sysparm_fields=sys_id,approver&sysparm_exclude_reference_link=true")[1].get("result", [])
    log(f"  approval rows requested: {len(rows)}")
    if mode == "auto":
        agent = find("sys_user", "user_name=" + os.environ.get("SN_APPROVER_USER", "release.approval.agent"), ["sys_id"]).get("sys_id", "")
        done = 0
        # A change can need several approval groups; the next group's rows appear after the previous group approves.
        # The agent approves every row it owns, then looks again, until the change itself is approved.
        for _ in range(12):
            if val(read("change_request", cid, ["approval"]).get("approval")) == "approved": break
            mine = call("GET", f"/api/now/table/sysapproval_approver?sysparm_query=sysapproval={cid}^approver={agent}^state=requested&sysparm_fields=sys_id&sysparm_exclude_reference_link=true", who="approver")[1].get("result", [])
            for x in mine:
                s, r = call("PATCH", f"/api/now/table/sysapproval_approver/{x['sys_id']}", {"state": "approved", "comments": f"Auto-approved by the Release approval agent. Risk score {score}, below the human-approval threshold. {gates_note}"}, who="approver")
                log(f"  agent approval row -> HTTP {s} {r.get('error', '')}"); done += 1
            time.sleep(10)
        if not done: sys.exit("the release approval agent has no approval row on this change (is it a member of the approving group?)")
        if val(read("change_request", cid, ["approval"]).get("approval")) != "approved":
            sys.exit("the agent approved its rows but the change still lacks approval; another approver is needed, release stopped")
        return "approved by the release approval agent"
    log(f"  high risk (score {score}): waiting up to {HUMAN_WAIT_MIN} min for a person to approve {cid} in ServiceNow")
    end = time.time() + HUMAN_WAIT_MIN * 60
    while time.time() < end:
        a = val(read("change_request", cid, ["approval"]).get("approval"))
        if a == "approved": return "approved by a person"
        if a == "rejected": sys.exit("the change was rejected by a person; release stopped")
        time.sleep(20)
    sys.exit("no human approval within the wait window; release stopped")

def walk_change(cid, me, defaults, close_code=None, notes="", target="-1", mode="auto", score=0, gates_note=""):
    approved_by = ""
    stuck = {}
    for _ in range(40):
        cur = st("change_request", cid)
        if cur == target or (target == "3" and cur == "3"): return approved_by
        nxt = ORDER[ORDER.index(cur) + 1]
        stuck[cur] = stuck.get(cur, 0) + 1
        if stuck[cur] > 8: sys.exit(f"change stuck in state {cur} before {nxt}")
        t = transition(cid, nxt)
        if t and not t.get("transition_available"):
            blocked = [c["condition"].get("name", "") for c in t.get("conditions", []) if not c.get("passed")]
            miss = [f for c in t.get("conditions", []) if not c.get("passed") for f in c["condition"].get("mandatory_fields", [])]
            if any("Change Task" in x for x in blocked): close_change_tasks(cid, me); continue
            if any("Approved by" in x for x in blocked):
                if not approved_by: approved_by = request_approval(cid, mode, score, gates_note)
                time.sleep(5); continue
            fill = {f: defaults[f] for f in miss if f in defaults}
            if nxt == "3": fill.update({"close_code": close_code, "close_notes": notes})
            if not fill: sys.exit(f"change blocked before {nxt}: {blocked}")
            patch("change_request", cid, fill); continue
        extra = {"close_code": close_code, "close_notes": notes} if nxt == "3" else {}
        patch("change_request", cid, {"state": nxt, **extra})
        time.sleep(2)
    sys.exit("change did not reach the target state")

def problem_to(pid, to, **fields):
    """The Stable Loop endpoint: fields and state go in one call, the endpoint saves fields first and asks ServiceNow whether the move is allowed."""
    s, r = call("POST", f"{API}/problem/{pid}/state", {"state": to, **fields})
    if s != 200: sys.exit(f"problem state {to} refused: HTTP {s} {r.get('error')}")


# ---------- modes ----------
def open_change():
    policy = json.load(open("e2e/policy.json"))
    files = changed_files(); score = risk_score(policy, files); mode = decide(policy, score)
    fixes = fix_trailer()
    log(f"risk score {score} ({len(files)} files, tier {policy.get('tier')}) -> {mode} approval" + (f"; this release fixes {fixes}" if fixes else ""))
    me = whoami(); grp = find("sys_user_group", "name=" + GROUP_NAME, ["sys_id"]).get("sys_id", "")
    if not (me and grp): sys.exit("could not resolve the pipeline user or the assignment group")
    gates = "Gates passed: tests with coverage, learned gates."
    chg = create("change_request", {"short_description": f"[LOOP {os.environ.get('GITHUB_RUN_ID', '')}] Release {os.environ.get('GITHUB_REF_NAME', '')}" + (f" (fix for {fixes})" if fixes else ""),
        "type": "normal", "category": "Software", "assigned_to": me,
        "description": f"Pipeline run: {RUN_URL}\nCommit: {os.environ.get('GITHUB_SHA', '')}\nRisk score: {score}\nApproval path: {mode}\n{gates}"})
    patch("change_request", chg["sys_id"], {"assignment_group": grp})
    start = datetime.datetime.now(datetime.timezone.utc)
    defaults = {"assignment_group": grp, "assigned_to": me, "start_date": (start + datetime.timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"),
                "end_date": (start + datetime.timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S"), "justification": "Automated release", "implementation_plan": "Deploy via pipeline",
                "backout_plan": "Automatic rollback to the last good deployment", "test_plan": "Soak test against the SLO", "risk": "3", "impact": "3", "category": "Software"}
    log(f"change {chg['number']} opened")
    work_note("change_request", chg["sys_id"], f"Release approval agent: risk score {score}, path {mode}. {gates}")
    approved_by = walk_change(chg["sys_id"], me, defaults, target="-1", mode=mode, score=score, gates_note=gates)
    link = []
    if fixes:
        prb = find("problem", "number=" + fixes, ["sys_id"])
        if prb.get("sys_id"): patch("problem", prb["sys_id"], {"rfc": chg["sys_id"]}); link.append(prb["sys_id"])
    json.dump({"change": chg["sys_id"], "number": chg["number"], "fixes": fixes, "problem": link[0] if link else "", "me": me, "grp": grp, "defaults": defaults}, open(STATE_FILE, "w"))
    out("change_number", chg["number"]); out("approval_path", mode); out("approved_by", approved_by or "n/a")

def load(): return json.load(open(STATE_FILE))

def close_ok():
    s = load(); me = s["me"]
    walk_change(s["change"], me, s["defaults"], close_code="successful", notes="Soak passed within SLO; release stable", target="3")
    log(f"change {s['number']} closed successful")
    if s["problem"]:
        prb = read("problem", s["problem"], ["number", "first_reported_by_task", "description"])
        inc = val(prb.get("first_reported_by_task"))
        if inc:
            patch("incident", inc, {"state": "2", "assigned_to": me})
            patch("incident", inc, {"state": "6", "close_code": PERM_FIX, "close_notes": f"Permanent fix {s['number']} held in soak ({RUN_URL})."})
            log(f"incident resolved: state {st('incident', inc)}")
        problem_to(s["problem"], "103")
        problem_to(s["problem"], "104", cause_notes="Root cause removed by the permanent fix", fix_notes=f"Fix {s['number']} deployed through the same gates ({RUN_URL})")
        problem_to(s["problem"], "106", resolution_code="fix_applied")
        problem_to(s["problem"], "107")
        log(f"problem {prb.get('number')} closed: state {st('problem', s['problem'])}")
        m = re.search(r"/issues/(\d+)", prb.get("description", "") or "")
        if m and REPO: subprocess.run(["gh", "issue", "close", m.group(1), "-R", REPO, "-c", f"Closed: fix {s['number']} held in soak ({RUN_URL})"], check=False)

def close_fail():
    s = load(); me, grp = s["me"], s["grp"]
    walk_change(s["change"], me, s["defaults"], close_code="unsuccessful", notes="Soak breached the SLO; rolled back automatically", target="3")
    log(f"change {s['number']} closed unsuccessful")
    inc = create("incident", {"short_description": f"[LOOP {os.environ.get('GITHUB_RUN_ID', '')}] SLO breach after release {os.environ.get('GITHUB_REF_NAME', '')}", "impact": "1", "urgency": "1",
                              "description": f"Soak SLO breach, rolled back. Pipeline run: {RUN_URL}"})
    patch("incident", inc["sys_id"], {"parent": s["change"]})
    case_url = ""
    if REPO:
        r = subprocess.run(["gh", "issue", "create", "-R", REPO, "-t", f"GIT case: SLO breach after {s['number']}", "-b", f"Incident {inc['number']}, change {s['number']}. Pipeline run: {RUN_URL}"], capture_output=True, text=True)
        case_url = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""
    prb = create("problem", {"short_description": f"[LOOP {os.environ.get('GITHUB_RUN_ID', '')}] RCA: SLO breach after {s['number']}", "first_reported_by_task": inc["sys_id"], "assigned_to": me, "assignment_group": grp,
                             "description": f"GIT case (GitHub issue): {case_url}\nPipeline run: {RUN_URL}"})
    log(f"incident {inc['number']}, problem {prb['number']}, GIT case {case_url}")
    out("incident", inc["number"]); out("problem", prb["number"]); out("git_case", case_url)


def check_auth():
    """Try each identity's token request and report only the status (never the token)."""
    for who in ("pipeline", "approver"):
        pre = "SN_CLIENT" if who == "pipeline" else "SN_APPROVER_CLIENT"
        cid, sec = os.environ.get(f"{pre}_ID", ""), os.environ.get(f"{pre}_SECRET", "")
        log(f"{who}: client id length {len(cid)}, secret length {len(sec)}, id ends ...{cid[-4:]}")
        body = urllib.parse.urlencode({"grant_type": "client_credentials", "client_id": cid, "client_secret": sec}).encode()
        try:
            with urllib.request.urlopen(urllib.request.Request(BASE + "/oauth_token.do", data=body, headers={"Content-Type": "application/x-www-form-urlencoded"}), timeout=40) as r:
                j = json.loads(r.read()); log(f"{who}: HTTP {r.status}, got a token: {'access_token' in j}")
        except urllib.error.HTTPError as e: log(f"{who}: HTTP {e.code} {e.read().decode()[:160]}")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    {"open-change": open_change, "close-ok": close_ok, "close-fail": close_fail, "check-auth": check_auth}.get(mode, lambda: sys.exit(__doc__))()
