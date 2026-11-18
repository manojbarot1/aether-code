"""The project status panel: what the current (or last) job in a session is doing, built from the session's own
messages so it also works for finished jobs and after a restart.

status(rows, live) -> dict with: request, project, state, phase, steps, started/updated, requirements, tasks,
team, checks, timeline, final, advice. `rows` are the session's messages (oldest first); `live` carries what
only the running engine knows (who is busy right now, file owners, which agents are down, the project folder).
"""
from __future__ import annotations

import re
from pathlib import Path

PHASES = [("plan", "Plan"), ("work", "Build"), ("test", "Test"), ("verify", "Verify"), ("fix", "Fix"), ("summary", "Summary")]
PHASE_OF = {"Plan": "plan", "Work": "work", "Test": "test", "Verify": "verify", "Fix": "fix", "Summary": "summary",
            "Quick": "work", "Deep": "plan", "Standard": "plan"}
TASK_RE = re.compile(r"^\s*@([\w .-]+?)\s*[:\-–]\s*(.+)$", re.M)
REQ_RE = re.compile(r"^\s*[-*]?\s*\**(R\d+)\**\s*[:.)\-–]\s*(.+)$", re.M)


def _short(t: str, n: int = 90) -> str:
    t = re.sub(r"\s+", " ", t or "").strip()
    return t if len(t) <= n else t[: n - 1] + "…"


def _files_of(task: str) -> list[str]:
    m = re.search(r"\bfiles?\s*:\s*(.+?)(?:\s+ALSO:|$)", task, re.I)
    if not m:
        return []
    out = []
    for raw in re.split(r"[,;]\s*|\s+(?:and|&)\s+", m.group(1)):
        f = raw.strip().strip("`'\"*()[]").rstrip(".").strip()
        if f and " " not in f and ("." in f or f.endswith("/")):
            out.append(f)
    return out


def _checks(text: str) -> list[dict]:
    out = []
    for block in ("\n" + text).split("\n$ ")[1:]:
        head = block.split("\n", 1)[0].strip()
        name = head.split("   (")[0]
        failed = "[FAIL" in block or "RESULT: FAIL" in block
        passed = "[PASS" in block or "RESULT: PASS" in block
        first = next((ln[6:].strip() for ln in block.splitlines() if ln.startswith("FAIL  ")), "")
        if failed and not first:
            first = next((ln.strip() for ln in reversed(block.splitlines()) if ln.strip() and not ln.startswith("[")), "")
        label = ("Browser check" if "verify_web" in name else "Contract check" if name.startswith("contract") else
                 "Deliverables" if name.startswith("deliverables") else "Acceptance tests" if name.startswith("acceptance") else
                 "Tests" if re.search(r"test|unittest|pytest", name) else "Compile" if "compileall" in name else _short(name, 40))
        if "--steps" in name:
            label = "Browser + acceptance steps"
        n_fail = sum(1 for ln in block.splitlines() if ln.startswith("FAIL  "))
        out.append({"name": label, "cmd": _short(name, 120), "ok": passed and not failed, "detail": _short(first, 200),
                    "fails": n_fail})
    return out


def status(rows: list[dict], live: dict) -> dict:
    users = [i for i, m in enumerate(rows) if m["role"] == "user" and not (m.get("meta") or {}).get("during_job")]
    if not users:
        return {"empty": True}
    turn = rows[users[-1]:]
    t0 = turn[0]["ts"]
    request = turn[0]["content"]
    sysm = [m for m in turn if m["role"] == "system"]
    asst = [m for m in turn if m["role"] == "assistant" and (m.get("meta") or {}).get("phase") != "status"]
    shell = [m for m in turn if m["role"] == "shell"]
    running = bool(live.get("running"))

    # ── what kind of job, and where it stands
    kind = next((m["content"].split(" · ")[0] for m in sysm if m["author"] == "Team" and
                 m["content"].split(" · ")[0] in ("Quick", "Standard", "Deep", "Answer")), "")
    if not kind and not any(m["meta"].get("phase") for m in asst):
        kind = "Answer"
    project = next((m["content"].split(": ", 1)[1] for m in sysm if m["content"].startswith("Working in a new project folder")),
                   live.get("cwd") or "")
    phase_seen, phase, rounds = [], "", 0
    for m in sysm:
        if m["author"] != "Team":
            continue
        head = m["content"].split(" · ")[0]
        p = PHASE_OF.get(head)
        if p:
            phase = p
            if p not in phase_seen:
                phase_seen.append(p)
            if p == "fix":
                rounds += 1
    final = next((m["content"] for m in reversed(sysm) if m["content"].startswith("Final check:")), "")
    stopped = any("Stopped" == (m["meta"] or {}).get("error") for m in asst) and not running
    summarized = any(m["meta"].get("phase") == "summary" for m in asst)
    team_job = kind in ("Quick", "Standard", "Deep")
    state = ("running" if running else "passed" if final.startswith("Final check: PASSED") else
             "failed" if final.startswith("Final check: FAILED") else "stopped" if stopped else
             "interrupted" if team_job and phase and phase != "summary" and not summarized else "done")
    steps = []
    for key, label in PHASES:
        if key == "test" and "test" not in phase_seen:
            continue
        if key == "fix" and "fix" not in phase_seen:
            continue
        st = "done" if key in phase_seen and key != phase else "now" if key == phase and running else (
            "done" if key == phase else "todo")
        steps.append({"key": key, "label": label + (f" ×{rounds}" if key == "fix" and rounds > 1 else ""), "state": st})

    # ── plan: requirements and tasks
    plan = next((m["content"] for m in reversed(asst) if m["meta"].get("phase") == "plan" and TASK_RE.search(m["content"])), "")
    if plan and "## Tasks" not in plan:   # tasks re-asked separately: join the two plan replies
        parts = [m["content"] for m in asst if m["meta"].get("phase") == "plan"]
        plan = "\n\n".join(parts[-2:])
    summary = next((m["content"] for m in reversed(asst) if m["meta"].get("phase") == "summary"), "")
    req_status = {}
    sec = summary.split("## Requirements", 1)[1].split("\n## ", 1)[0] if "## Requirements" in summary else ""
    for ln in sec.splitlines():
        r = re.search(r"\b(R\d+)\b", ln)
        if r:
            req_status[r.group(1)] = "ok" if "✓" in ln or "✅" in ln else "bad" if "✗" in ln or "❌" in ln or "✕" in ln else "unknown"
    reqs, seen = [], set()
    req_block = plan.split("## Requirements", 1)[1].split("\n## ", 1)[0] if "## Requirements" in plan else plan
    for rid, text in REQ_RE.findall(req_block):
        if rid in seen:
            continue
        seen.add(rid)
        reqs.append({"id": rid, "text": _short(text, 140), "state": req_status.get(rid, "pending" if running else "unknown")})

    names = {e["name"]: e for e in live.get("engineers", [])}
    busy = set(live.get("busy_names", []))
    root = Path(project).expanduser() if project and live.get("local", True) else None
    tasks = []
    task_block = plan.split("## Tasks", 1)[1].split("\n## ", 1)[0] if "## Tasks" in plan else plan
    for who, text in TASK_RE.findall(task_block):
        who = who.strip()
        if who not in names and not any(who.lower() == n.lower() for n in names):
            continue
        tasks.append({"owner": who, "first": who, "text": _short(re.split(r"\s*\|\s*files?\s*:", text, flags=re.I)[0], 120),
                      "files": [{"path": f, "ok": bool(root and (root / f).exists())} for f in _files_of(text)]})
    merged = next((int(x.group(1)) for m in sysm if (x := re.search(r"merged it into (\d+) tasks", m["content"]))), 0)
    if merged and len(tasks) > merged:   # Aether folded the extra tasks into the first ones
        for k, extra in enumerate(tasks[merged:]):
            host = tasks[k % merged]
            host["text"] = _short(host["text"] + " + " + extra["text"], 160)
            host["files"] += extra["files"]
        tasks = tasks[:merged]
    for m in sysm:   # reassignments move a task to another engineer
        r = re.match(r"Reassigned · (.+?) is unavailable \((.*?)\) — (.+?) takes over the (?:task “(.+?)”|(.+?))\.?$", m["content"])
        if r:
            old, why, new, what = r.group(1), r.group(2), r.group(3), r.group(4) or ""
            if not what:          # the lead role, a summary or a fix: not a planned task
                continue
            for t in tasks:
                if t["owner"] == old and (t["text"][:25].lower() in what.lower() or what.lower()[:25] in t["text"].lower()):
                    t["owner"], t["reassigned"] = new, f"from {old} ({_short(why, 50)})"
    for t in tasks:
        replies = [m for m in asst if m["author"] == t["owner"] and m["meta"].get("phase") in ("work", "fix")]
        files_ok = all(f["ok"] for f in t["files"]) if t["files"] else None
        t["state"] = ("working" if t["owner"] in busy and phase in ("work", "fix") else
                      "done" if replies and files_ok is not False else
                      "incomplete" if replies and files_ok is False else "waiting" if running else "not started")

    # ── who did what
    team = []
    for nm in dict.fromkeys(m["author"] for m in asst):
        mine = [m for m in asst if m["author"] == nm]
        cmds = [m for m in shell if m["meta"].get("by") == nm and not m["content"].startswith("$ write ")]
        writes = [m for m in shell if m["meta"].get("by") == nm and m["content"].startswith("$ write ")]
        written = sorted({ln[2:].split(" (")[0] for m in writes for ln in m["content"].splitlines() if ln.startswith("✓ ")})
        nudges = sum(1 for m in sysm if m["content"].startswith(nm + " replied without") or m["content"].startswith(nm + " wrote a tool call"))
        problems = [m["content"] for m in sysm if m["content"].startswith(f"Reassigned · {nm} is unavailable")
                    or m["content"].startswith(f"{nm} is unavailable")]
        roles = []
        for m in mine:
            ph = m["meta"].get("phase") or "reply"
            lab = {"plan": "lead", "work": "builder", "test": "tester", "verify": "verifier", "fix": "fixer", "summary": "lead",
                   "build": "builder"}.get(ph, ph)
            if lab not in roles:
                roles.append(lab)
        last = mine[-1]
        e = names.get(nm, {})
        now = ("working" if nm in busy else "unavailable" if live.get("down", {}).get(e.get("id", "")) else
               "failed" if (last["meta"] or {}).get("error") and (last["meta"] or {}).get("error") != "Stopped" else "idle")
        team.append({"name": nm, "color": e.get("color", "#888"), "avatar": e.get("avatar", ""), "roles": roles,
                     "now": now, "why": live.get("down", {}).get(e.get("id", ""), ""), "replies": len(mine), "commands": len(cmds),
                     "files": written[:30], "nudges": nudges, "problems": len(problems),
                     "active_s": round(sum((m["meta"] or {}).get("dur") or 0 for m in mine)),
                     "last": _short(re.sub(r"```.*?```", "", last["content"], flags=re.S), 110), "last_ts": last["ts"]})

    # ── checks and timeline
    checks_msgs = [m for m in shell if m["author"] == "Aether checks"]
    checks = _checks(checks_msgs[-1]["content"]) if checks_msgs else []
    history = [{"t": m["ts"] - t0, "ok": all(c["ok"] for c in _checks(m["content"]))} for m in checks_msgs]
    timeline = []
    for m in turn[1:]:
        c = m["content"] or ""
        if m["role"] == "system" and m["author"] in ("Team", "Aether"):
            if c.startswith(("Working in", "Stopped servers")):
                continue
            kind_ = ("phase" if m["author"] == "Team" and " · " in c[:14] and not c.startswith("Reassigned") else
                     "warn" if re.search(r"unavailable|Reassigned|not written|without running|tool call|FAIL|Blocked|Still failing|treating it as FAIL", c)
                     else "ok" if "PASSED" in c else "info")
            timeline.append({"t": round(m["ts"] - t0), "kind": kind_, "text": _short(c, 160)})
        elif m["role"] == "user":
            timeline.append({"t": round(m["ts"] - t0), "kind": "info", "text": "You: " + _short(c, 140)})
        elif m["author"] == "Aether checks":
            cs = _checks(c)
            bad = [x["name"] for x in cs if not x["ok"]]
            timeline.append({"t": round(m["ts"] - t0), "kind": "bad" if bad else "ok",
                             "text": "Automatic checks: " + ("failed — " + ", ".join(bad) if bad else "all passed")})
    timeline = timeline[-60:]

    # ── what could be better
    advice = []

    def tip(level, text, prompt=None):
        advice.append({"level": level, "text": text, "prompt": prompt})
    if state == "interrupted":
        tip("act", "The job stopped before it finished (the chat was restarted or stopped). The files so far are kept; "
                   "ask the team to carry on.", "Continue the job: fix the failing checks, then verify again.")
    if state == "failed":
        bad = [c["name"] for c in checks if not c["ok"]]
        tip("act", "The job ended with failing checks" + (f" ({', '.join(bad)})" if bad else "") + ". Ask the team to carry on from here.",
            "Fix the failing checks listed in the last automatic checks, then verify again.")
    missing_req = [r["id"] for r in reqs if r["state"] == "bad"]
    if missing_req and not running:
        tip("act", f"Requirements not met: {', '.join(missing_req)}.", f"Finish requirements {', '.join(missing_req)} and verify them.")
    quota = [p for p in team if p["problems"] or p["now"] == "unavailable"]
    for p in quota:
        if p["problems"] >= 1 and any(w in (p["why"] + " ".join(m["content"] for m in sysm if p["name"] in m["content"])).lower()
                                      for w in ("quota", "429", "rate")):
            tip("warn", f"{p['name']} hit provider limits (quota / rate limit). Results get worse until quotas reset; "
                        "make a less-used agent the lead in the Agents tab.")
            break
    stalls = sum(1 for m in sysm if m["content"].startswith("Reassigned"))
    if stalls >= 2:
        tip("warn", f"{stalls} hand-overs: agents stopped responding mid-task. Fewer, steadier agents usually finish faster.")
    nudges = sum(p["nudges"] for p in team)
    if nudges >= 3:
        tip("info", f"Agents needed {nudges} reminders to actually act. Short, numbered requirements help models follow the brief.")
    if rounds >= 3:
        tip("info", "Three repair rounds were needed. Splitting a big request into smaller follow-ups (e.g. 'now add drag and drop') "
                    "converges more reliably.")
    if checks and not any(c["name"] in ("Tests",) for c in checks) and kind in ("Standard", "Deep") and not running:
        tip("info", "No unit tests were found, so only the build and browser checks proved it works.", "Add unit tests for the core logic and run them.")
    if any(c["name"].startswith("Browser") for c in checks) and not any("steps" in c["name"] for c in checks) and kind in ("Standard", "Deep"):
        tip("info", "No browser acceptance steps ran, so features were only smoke-tested.")
    if state == "passed":
        tip("ok", "All checks passed. Good next steps: a code review pass, or more tests for edge cases.",
            "Review the code for bugs, edge cases and clarity; fix what you find and keep all checks passing.")
    dur = (turn[-1]["ts"] - t0)
    if dur > 1800 and not running:
        tip("info", f"This job took {round(dur / 60)} minutes. Large briefs go faster as 2–3 smaller requests.")

    return {"request": _short(request, 400), "project": project, "kind": kind, "state": state, "phase": phase,
            "running": running, "steps": steps, "started": t0, "updated": turn[-1]["ts"], "elapsed": round(dur),
            "requirements": reqs, "tasks": tasks, "team": team, "checks": checks, "check_history": history,
            "timeline": timeline, "final": final, "advice": advice[:6]}


def status_text(d: dict) -> str:
    """A short markdown status for the chat (answer to "status?" during a job)."""
    if not d or d.get("empty"):
        return "No job has started in this session yet."
    if d.get("error"):
        return "Status unavailable: " + d["error"]
    import time as _t
    el = (_t.time() - d["started"]) if d["running"] else d["elapsed"]
    el = int(el)
    dur = f"{el // 60}m {el % 60:02d}s" if el >= 60 else f"{el}s"
    cur = next((s_["label"] for s_ in d["steps"] if s_["state"] == "now"), d.get("phase") or "—")
    out = [f"**Status · {dur}** — " + (f"running, now in **{cur}**" if d["running"] else d["state"])]
    if d["tasks"]:
        by = lambda st: [t for t in d["tasks"] if t["state"] == st]
        w, dn, miss = by("working"), by("done"), by("incomplete")
        line = f"- Tasks: **{len(dn)}/{len(d['tasks'])} done**"
        if w:
            line += " · in progress: " + "; ".join(f"{t['owner']} ({t['text'][:60]})" for t in w)
        if miss:
            line += " · files missing: " + ", ".join(t["owner"] for t in miss)
        out.append(line)
    wk = [p for p in d["team"] if p["now"] == "working"]
    if wk:
        out.append("- Working now: " + ", ".join(p["name"] + (f" ({p['roles'][-1]})" if p["roles"] else "") for p in wk))
    un = [p for p in d["team"] if p["now"] == "unavailable"]
    if un:
        out.append("- Unavailable: " + ", ".join(p["name"] for p in un))
    if d["checks"]:
        out.append("- Latest checks: " + " · ".join(("✅ " if c["ok"] else "❌ ") + c["name"] for c in d["checks"]))
        out += [f"  - {c['name']}: {c['detail'] or 'failed'}" for c in d["checks"] if not c["ok"]]
    if d.get("final"):
        out.append("- " + d["final"])
    out += ["", "Full details: the 📊 Project panel on the right."]
    return "\n".join(out)
