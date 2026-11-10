"""Late detection: a defect that the pipeline missed is reported afterwards (monitoring or a customer). Opens the incident,
the GIT case and the problem against the original change, the same records the pipeline would have opened on a rollback."""
import json, os, subprocess, sys
sys.path.insert(0, "e2e"); import loop
d = json.load(open("e2e2/late.json"))
me = loop.whoami(); grp = loop.find("sys_user_group", "name=" + loop.GROUP_NAME, ["sys_id"]).get("sys_id", "")
chg = loop.find("change_request", "number=" + d["change"], ["sys_id"])["sys_id"]
inc = loop.create("incident", {"short_description": f"[LOOP late] {d['class']} defect found after release {d['change']}", "impact": "2", "urgency": "2",
                               "description": f"Defect reported after release (class {d['class']}). Pipeline run: {loop.RUN_URL}"})
loop.patch("incident", inc["sys_id"], {"parent": chg})
case = subprocess.run(["gh", "issue", "create", "-R", loop.REPO, "-t", f"GIT case: {d['class']} defect after {d['change']}", "-b", f"Incident {inc['number']}, change {d['change']}. Pipeline run: {loop.RUN_URL}"], capture_output=True, text=True).stdout.strip().splitlines()[-1]
prb = loop.create("problem", {"short_description": f"[LOOP late] RCA: {d['class']} defect after {d['change']}", "first_reported_by_task": inc["sys_id"], "assigned_to": me, "assignment_group": grp,
                              "description": f"GIT case (GitHub issue): {case}\nPipeline run: {loop.RUN_URL}"})
loop.log(f"incident {inc['number']}, problem {prb['number']}, GIT case {case}")
loop.out("incident", inc["number"]); loop.out("problem", prb["number"]); loop.out("git_case", case)
