#!/usr/bin/env python3
"""RAGA. Run with no arguments to open the launcher window.

  python raga.py                          open the two-button launcher
  python raga.py demo                     the full learning loop on made-up data (no account needed)
  python raga.py doctor                   is Claude Code installed and logged in?
  python raga.py lesson add --trigger "..." --action "..." --why "..." [--bad "..."]
  python raga.py lesson reinforce|harmful|retire LESSON_ID
  python raga.py playbook                 show the current lessons
  python raga.py eval --live              A/B eval of the demo lesson against real Claude
  python raga.py council "question" [--context "..."]   run the council with real Claude
  python raga.py export [--out DIR]       training data: SFT, preference pairs, evals, council
  python raga.py hook session-start|prompt   (called by Claude Code, see README)
  python raga.py hooks-snippet            print the settings.json block that turns the hooks on

Data lives in ~/.raga/data (override with RAGA_HOME).
"""
import argparse
import os
import re
import sys
from pathlib import Path

from raga import claude_cli, council, evals, export, hooks
from raga import lessons as L
from raga.store import Store


def store():
    return Store(Path(os.environ.get("RAGA_HOME") or Path.home() / ".raga") / "data")


def slug(text):
    return "-".join(re.findall(r"[a-z0-9]+", text.lower())[:4]) or "lesson"


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")   # Windows consoles default to cp1252; lessons use arrows
    p = argparse.ArgumentParser(prog="raga", description="RAGA launcher and learning engine")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("demo")
    sub.add_parser("doctor")
    sub.add_parser("playbook")
    sub.add_parser("hooks-snippet")
    le = sub.add_parser("lesson")
    le.add_argument("op", choices=["add", "reinforce", "harmful", "retire"])
    le.add_argument("lesson_id", nargs="?")
    for flag in ("--trigger", "--action", "--why", "--bad", "--evidence"):
        le.add_argument(flag, default="")
    ev = sub.add_parser("eval")
    ev.add_argument("--live", action="store_true", help="use real Claude (costs usage)")
    co = sub.add_parser("council")
    co.add_argument("question")
    co.add_argument("--context", default="")
    ex = sub.add_parser("export")
    ex.add_argument("--out", default="raga-export")
    hk = sub.add_parser("hook")
    hk.add_argument("which", choices=["session-start", "prompt"])
    a = p.parse_args(argv)

    if a.cmd is None:
        from raga import launcher   # imported lazily: tkinter isn't needed for any other command
        return launcher.main()
    if a.cmd == "demo":
        from raga import demo
        demo.run()
    elif a.cmd == "doctor":
        s = claude_cli.check()
        print(s.detail + ("" if s.installed else "\n\n" + claude_cli.INSTALL_HELP.get(
            __import__("platform").system(), claude_cli.INSTALL_HELP["Linux"])))
        return 0 if s.installed else 1
    elif a.cmd == "playbook":
        print(L.playbook(store()))
    elif a.cmd == "hooks-snippet":
        print(hooks.SETTINGS_SNIPPET % {"raga": str(Path(__file__).resolve()).replace("\\", "\\\\")})
    elif a.cmd == "lesson":
        st = store()
        if a.op == "add":
            if not (a.trigger and a.action):
                p.error("lesson add needs --trigger and --action")
            lid = a.lesson_id or slug(a.trigger)
            st.append("lesson_op", {"op": "add", "lesson_id": lid, "trigger": a.trigger, "action": a.action,
                                    "why": a.why, "bad_action": a.bad, "evidence": a.evidence})
            print("added %s (trial until reinforced %d times)" % (lid, L.PROMOTE_AT))
        else:
            if a.lesson_id not in L.lessons(st):
                p.error("no lesson %r" % a.lesson_id)
            st.append("lesson_op", {"op": a.op, "lesson_id": a.lesson_id, "evidence": a.evidence})
            print("%s %s" % (a.op, a.lesson_id))
    elif a.cmd == "eval":
        from raga import demo
        if not a.live:
            p.error("use `demo` for the scripted run, or `eval --live` for real Claude")
        tmp = Store(Path(os.environ.get("RAGA_HOME") or Path.home() / ".raga") / "eval-live")
        lesson = dict(demo.DEMO_LESSONS[0], id=demo.DEMO_LESSONS[0]["lesson_id"])
        res = evals.run_ab(tmp, lesson, demo.DEMO_CASES[lesson["id"]], evals.ClaudeModel())
        print("REAL Claude, lesson [%s]: cases %d, without %.2f, with %.2f, lift %+.2f -> %s"
              % (lesson["id"], res["cases"], res["without"], res["with"], res["lift"], res["verdict"]))
    elif a.cmd == "council":
        result = council.run(a.question, evals.ClaudeModel(), context=a.context)
        if result["missing"]:
            print("Missing advisors: %s" % ", ".join(result["missing"]))
        print(result["verdict"])
        decision = input("\nYour call, in your own words (Enter to skip saving): ").strip()
        if decision:
            followed = input("Did you follow the verdict? [y/n]: ").strip().lower().startswith("y")
            council.record(store(), result, decision, followed)
            print("saved")
    elif a.cmd == "export":
        m = export.export(store(), a.out)
        for name, n in m["counts"].items():
            print("  %-24s %d" % (name, n))
    elif a.cmd == "hook":
        hooks.main(store(), a.which)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
