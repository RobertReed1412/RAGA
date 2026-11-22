"""`python raga.py demo`: the whole learning loop on made-up data, in a throwaway folder, in ~1 second.

HONEST LABEL: the demo's "model" is a scripted stand-in (it follows a lesson when given one), so the
demo proves the PIPELINE works: store → playbook → retrieval → A/B eval → council → export. It does
not prove a lesson helps a real model. For that, run `python raga.py eval --live` (uses Claude).
"""
import random
import tempfile
from pathlib import Path

from . import council, evals, export, hooks
from . import lessons as L
from .store import Store

# Synthetic lessons, written like real ones: situation → better action → why, plus what was done instead.
DEMO_LESSONS = [
    {"lesson_id": "rerun-failed-only", "kind": "fix", "domain": "dev",
     "trigger": "a slow test suite has one failing test after a small fix",
     "action": "rerun only the failing tests, batch the fixes, then do one final full run",
     "bad_action": "rerun the full suite after every small fix",
     "why": "full reruns after each fix wasted ~20 minutes; the failed-only rerun took ~40 seconds"},
    {"lesson_id": "break-it-on-purpose", "kind": "strategy", "domain": "dev",
     "trigger": "a new batch of tests passes on the very first run",
     "action": "break the feature on purpose and confirm the tests fail, then restore it",
     "bad_action": "trust the green run",
     "why": "a test that can't fail proves nothing"},
    {"lesson_id": "utf8-on-windows", "kind": "fix", "domain": "dev",
     "trigger": "writing text files from Python that must run on Windows",
     "action": "open files with encoding='utf-8' explicitly",
     "bad_action": "rely on the default encoding",
     "why": "Windows defaults to cp1252 and crashes on emoji or arrows"},
]
DEMO_REINFORCE = {"rerun-failed-only": 3, "break-it-on-purpose": 2, "utf8-on-windows": 1}
DEMO_CASES = {
    "rerun-failed-only": [
        evals.Case("slow-suite", "My test suite takes 8 minutes and one test failed. I just fixed it. What do I run next?",
                   must_include=[["only the fail", "only the test that failed", "just the fail", "--lf", "last failed"]],
                   must_not_include=["rerun the full suite now", "run the full suite now"]),
        evals.Case("three-fixes", "I have three small fixes for three failing tests in a 10-minute suite. Plan my test runs.",
                   must_include=[["batch", "all three fixes first", "fixes first", "apply all three"],
                                 ["at the end", "final full", "one full run", "full suite once", "once at the end"]]),
    ],
}
DEMO_COUNCIL = {
    "contrarian": "Option B fails if the extraction leaks personal data. Pick: B, carefully.",
    "assumptions": "Assumes reviewers will run it. Most likely wrong: they only read the README. Pick: B.",
    "expansionist": "Add a one-command demo so the claim is checkable. Pick: B.",
    "outsider": "Can a stranger verify it in two minutes? Pick: B with a GIF.",
    "executor": "1) fresh repo 2) privacy grep 3) demo command. Pick: B.",
}


def scripted_model(prompt, system=""):
    """Stand-in model: a generic answer, plus the lesson's action when the system prompt carries one."""
    answer = "Run the full suite now to be safe."
    for lesson in DEMO_LESSONS:
        if lesson["lesson_id"] in system:
            answer = "Rerun only the failing tests, batch the fixes, then do one final full run."
    return answer


def scripted_ask(prompt):
    for role, text in DEMO_COUNCIL.items():
        if prompt.startswith("You are the %s" % role.upper()):
            return text
    if prompt.startswith("You are a blind reviewer"):
        return "Ranking: 1, 3, 2, 5, 4. Weakest claim: 'reviewers will run it'. Unaddressed: licensing."
    return ("Verdict: B. Confidence: high. Strongest dissent: the launcher alone is thin, so lead with the "
            "engine. Next steps: fresh repo, privacy grep, demo command.")


def seed(store):
    for lesson in DEMO_LESSONS:
        store.append("lesson_op", dict(lesson, op="add", evidence="demo data"), source="demo")
        for n in range(DEMO_REINFORCE[lesson["lesson_id"]]):
            store.append("lesson_op", {"op": "reinforce", "lesson_id": lesson["lesson_id"],
                                       "evidence": "demo session %d" % (n + 1)}, source="demo")


def run(out=print):
    tmp = Path(tempfile.mkdtemp(prefix="raga-demo-"))
    store = Store(tmp / "data")
    seed(store)
    out("== 1. Playbook, rebuilt by replaying %d events ==" % len(store.events()))
    out(L.playbook(store))

    msg = "my tests are slow and one failing test is left, what next?"
    out("== 2. Retrieval: lessons injected for the message %r ==" % msg)
    out(hooks.prompt(store, msg) or "(none matched)")

    lesson = L.lessons(store)["rerun-failed-only"]
    res = evals.run_ab(store, lesson, DEMO_CASES["rerun-failed-only"], scripted_model)
    out("\n== 3. A/B eval of [rerun-failed-only] (DEMO: scripted model, shows the pipeline only) ==")
    out("cases: %(cases)d   without lesson: %(without).2f   with lesson: %(with).2f   lift: %(lift)+.2f   -> %(verdict)s" % res)

    result = council.run("Which portfolio option should I build: A, B or C?", scripted_ask,
                         rng=random.Random(7), parallel=False)
    council.record(store, result)   # undecided: no decision, so followed_verdict stays None
    out("\n== 4. Council (DEMO answers): %d advisors, blind order %s ==" % (len(result["advisors"]), result["blind_key"]))
    out(result["verdict"])

    manifest = export.export(store, tmp / "export")
    out("\n== 5. Export to training data: %s ==" % (tmp / "export"))
    for name, count in manifest["counts"].items():
        out("  %-24s %d rows" % (name, count))
    return {"dir": tmp, "eval": res, "manifest": manifest}
