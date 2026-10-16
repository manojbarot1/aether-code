"""Routing brain for Aether Lite / Code — ported from the web team's orchestrator (complexity.py + router.py).

* classify(text)            what kind of message is this? (question vs work)
* assess(text)              how much process does the work deserve? QUICK / STANDARD / DEEP (same factor table as the web app)
* choose_lead(...)          dynamic lead: capability match, model speed for the mode, recent reliability — never an engineer that is down
* mark_down / is_down       engineers that hit a session limit or lost their login are skipped for a while instead of wasting a turn
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

# ───────────────────────── availability
_DOWN: dict[str, tuple[float, str]] = {}
_FAILS: dict[str, list[float]] = {}
LIMIT_RE = re.compile(r"session limit|usage limit|rate.?limit|quota|hit your .{0,20}limit|out of (?:credits|messages)|credit balance|too many requests", re.I)
AUTH_RE = re.compile(r"authentication (?:failed|required)|not logged in|please run .{0,30}login|invalid or expired api key|unauthori[sz]ed|sign in", re.I)


def mark_down(eid: str, reason: str, secs: int) -> None:
    _DOWN[eid] = (time.time() + secs, reason[:160])


def down_reason(eid: str) -> str | None:
    d = _DOWN.get(eid)
    if d and d[0] > time.time():
        return d[1]
    _DOWN.pop(eid, None)
    return None


def is_down(eid: str) -> bool:
    return down_reason(eid) is not None


def clear_down(eid: str | None = None) -> None:
    _DOWN.pop(eid, None) if eid else _DOWN.clear()


def note_failure(eid: str, ok: bool) -> None:
    now = time.time()
    _FAILS[eid] = [t for t in _FAILS.get(eid, []) if now - t < 3600] + ([] if ok else [now])


def detect_outage(text: str) -> tuple[str, int] | None:
    """('why', seconds) if an engineer's output says it is out of quota / logged out."""
    if text and LIMIT_RE.search(text):
        return (text.strip().splitlines()[0][:140], 1800)
    if text and AUTH_RE.search(text):
        return ("signed out — sign in again", 600)
    return None


# ───────────────────────── request kind
BUILD_VERBS = re.compile(r"\b(build|create|make|implement|develop|write|generate|set ?up|install|deploy|start|run|launch|serve|fix|refactor|"
                         r"migrate|validate|re-?validate|test|add|change|update|rename|delete|remove|configure|convert|port|scaffold|design|restart|repair)\b", re.I)
QUESTION = re.compile(r"^\s*(what|why|how|when|where|who|which|can you|could you|is |are |does |do |did |explain|tell me|show me|summari[sz]e|"
                      r"give me (?:a |the )?(?:full )?(?:summary|overview|status|report)|list|any luck|status)\b", re.I)


def is_work(text: str) -> bool:
    t = text.strip()
    if QUESTION.search(t) and not re.search(r"\b(and|then)\s+(build|create|fix|start|run)\b", t, re.I):
        return False
    return bool(BUILD_VERBS.search(t))


# ───────────────────────── complexity (same factor table as the web app)
MODES = ("quick", "standard", "deep")
TH = {"quick_max": 24, "standard_max": 50}
_FACTORS = [
    ("database", 10, r"\b(database|postgres\w*|mysql|sqlite|mongo\w*|redis|orm)\b"),
    ("authentication", 10, r"\b(auth\w*|login|sign[- ]?in|sso|oauth|rbac|permissions?|users? accounts?)\b"),
    ("external APIs", 10, r"\b(integrat\w*|third[- ]party|external api|webhooks?|stripe|slack)\b"),
    ("multiple services", 10, r"\b(microservices?|multiple services|message queue|kafka|backend and (?:a )?frontend|full[- ]stack)\b"),
    ("infrastructure", 15, r"\b(kubernetes|k8s|terraform|ansible|helm|docker|cluster|infrastructure|vmware|vsphere|ec2|vpc)\b"),
    ("security requirements", 15, r"\b(secur\w*|compliance|encrypt\w*|audit (?:log|trail)|soc ?2|hipaa|gdpr|pen ?test|threat model)\b"),
    ("production deployment", 15, r"\b(production[- ]grade|production|high availability|multi[- ]region|zero[- ]downtime|enterprise)\b"),
    ("large migration", 25, r"\b(migrat\w+ \d{2,}|\d{2,} (?:vms?|servers|hosts|databases)|large[- ]scale migration|migration waves?)\b"),
    ("research", 15, r"\b(research|compare|evaluat\w+ (?:options|tools)|state of the art|survey|best approach)\b"),
    ("multiple systems", 20, r"\b(platform|multi[- ]tenant|saas|end[- ]to[- ]end system|several systems)\b"),
    ("monitoring / live data", 10, r"\b(monitor\w*|observability|real[- ]?time|live (?:data|metrics|updates)|alert\w*|telemetry)\b"),
    ("existing codebase", 10, r"\b(refactor\w*|existing (?:app\w*|code\w*|system|project)|legacy|rewrite)\b"),
    ("architecture design", 10, r"\b(design (?:a|an|the)? ?(?:\w+ ){0,3}architecture|architecture design|system design)\b"),
    ("AI/ML", 10, r"\b(ai[- ]powered|machine learning|\bml\b|llm|model training|embeddings?)\b"),
]
_SIMPLE = [
    ("simple single app", -10, r"\b(simple|small|tiny|basic|quick|little|single[- ]page|one[- ]page|(?:a|an) (?:\w+ ){0,4}(?:game|calculator|todo|to-do|landing page|script|converter|timer|clock|widget|portfolio|form|website|web ?site|page))\b"),
    ("few files", -5, r"\b(script|snippet|function|one file|single file|css|landing page|static (?:site|page)|sample pages?)\b"),
    ("small fix / follow-up", -12, r"^\s*(?:fix|add|change|update|rename|tweak|start|restart|run|validate|re-?validate|test|retry|try|stop|kill)\b"),
]


@dataclass
class Assessment:
    score: int
    mode: str
    why: list[str] = field(default_factory=list)


def assess(text: str) -> Assessment:
    low = " ".join(text.lower().split())
    score, why = 18, []
    for label, pts, pat in _FACTORS + _SIMPLE:
        if re.search(pat, low):
            score += pts
            why.append(f"{label} {pts:+d}")
    words = len(low.split())
    if words > 120:
        score += min(15, (words - 120) // 20 + 5)
        why.append(f"long brief {words}w")
    score = max(0, min(100, score))
    mode = "quick" if score <= TH["quick_max"] else "standard" if score <= TH["standard_max"] else "deep"
    return Assessment(score, mode, why)


# ───────────────────────── lead choice
TASK_TYPES = {
    "infrastructure": (("server", "docker", "container", "kubernetes", "deploy", "nginx", "network", "linux", "systemd", "cloud", "aws", "azure",
                        "terraform", "ansible", "ssh", "vm", "port", "restart", "disk"), ("infrastructure", "devops", "linux", "cloud", "architecture", "troubleshooting")),
    "application": (("app", "api", "backend", "frontend", "website", "web", "page", "code", "build", "implement", "feature", "refactor", "python",
                     "javascript", "typescript", "ui", "game", "site"), ("coding", "software_architecture", "backend", "development", "frontend", "debugging")),
    "research": (("research", "compare", "evaluate", "analyze", "data", "benchmark", "options", "document", "report", "summary"), ("research", "data", "documentation", "testing")),
    "security": (("security", "vulnerab", "audit", "harden", "auth", "secret", "credential", "tls"), ("security", "code_quality", "code_review")),
    "debugging": (("why", "error", "fails", "failing", "crash", "broken", "debug", "fix", "issue", "problem", "not working", "slow"), ("debugging", "troubleshooting", "code_quality")),
}
_ROLE_CAPS = {"architect": ["architecture", "infrastructure", "cloud", "devops", "code_review"], "developer": ["coding", "development", "frontend", "backend", "debugging"],
              "engineer": ["coding", "software_architecture", "debugging", "backend"], "research": ["research", "data", "documentation"],
              "software": ["coding", "software_architecture"], "devops": ["devops", "infrastructure", "linux"], "security": ["security", "code_review"]}
_FAST = re.compile(r"flash|haiku|mini\b|nano|lite\b|-low\b", re.I)
_STRONG = re.compile(r"opus|\bpro\b|ultra|thinking|120b|-high|max\b", re.I)


def caps_for(eng: dict) -> set[str]:
    if eng.get("caps"):
        return set(eng["caps"])
    caps: set[str] = set()
    for k, v in _ROLE_CAPS.items():
        if k in (eng.get("role") or "").lower():
            caps |= set(v)
    return caps or {"coding", "debugging"}


def tier(eng: dict) -> str:
    m = eng.get("model") or ""
    if _FAST.search(m):
        return "fast"
    if _STRONG.search(m) or (not m and eng.get("provider") == "claude_cli"):
        return "strong"
    return "balanced"


def task_type(text: str) -> str:
    words = set(re.findall(r"[a-z0-9]+", text.lower()))
    best, hits = "application", 0
    for name, (kws, _) in TASK_TYPES.items():
        n = sum(1 for k in kws if k in words or any(w.startswith(k) for w in words if len(k) > 4))
        if n > hits:
            best, hits = name, n
    return best


def choose_lead(text: str, engineers: list[dict], mode: str) -> tuple[dict, str]:
    """Best available engineer for this request. engineers = candidates (already filtered for availability)."""
    want = set(TASK_TYPES[task_type(text)][1])
    pref = {"quick": ("fast", "balanced", "strong"), "standard": ("balanced", "strong", "fast"), "deep": ("strong", "balanced", "fast")}[mode]
    best, best_s = engineers[0], -1e9
    for i, e in enumerate(engineers):
        s = 2.0 * len(caps_for(e) & want) - 0.05 * i                     # earlier in the sidebar wins ties
        s += (2 - pref.index(tier(e))) * 0.8                              # model speed/strength fits the job size
        s -= 1.5 * len(_FAILS.get(e["id"], []))                           # recent failures
        if s > best_s:
            best, best_s = e, s
    matched = sorted(caps_for(best) & want)
    return best, (", ".join(matched[:3]) or "general")


# ───────────────────────── the routing decision
@dataclass
class Route:
    kind: str                       # chat | quick | standard | deep
    lead: dict
    members: list[dict]             # lead first
    label: str


def route(text: str, candidates: list[dict], team_on: bool, explicit: list[dict] | None = None) -> Route:
    """Decide how much process this message gets."""
    if explicit:                                                          # the user named engineers: respect that
        return Route("standard" if len(explicit) > 1 and team_on else "chat", explicit[0], explicit if team_on else explicit, f"{', '.join(e['name'] for e in explicit)} asked directly")
    if not is_work(text):
        lead, why = choose_lead(text, candidates, "quick")
        return Route("chat", lead, [lead], f"Answer · {lead['name']} ({why})")
    a = assess(text)
    lead, why = choose_lead(text, candidates, a.mode)
    if a.mode == "quick" or not team_on or len(candidates) < 2:
        return Route("quick", lead, [lead], f"Quick · {lead['name']} builds, tests and starts it (score {a.score})")
    others = [e for e in candidates if e["id"] != lead["id"]]
    return Route(a.mode, lead, [lead] + others, f"{a.mode.title()} · {lead['name']} leads {', '.join(e['name'] for e in others)} (score {a.score}: {', '.join(a.why[:3]) or 'baseline'})")
