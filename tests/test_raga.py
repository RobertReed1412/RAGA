"""RAGA tests: stdlib unittest only, so anyone with Python can run them (no pip install).

  python -m unittest discover -s tests -v
"""
import contextlib
import io
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from raga import claude_cli, council, demo, evals, export, hooks  # noqa: E402
from raga import lessons as L  # noqa: E402
from raga.store import Store, redact  # noqa: E402


class TmpStore(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="raga-test-"))
        self.store = Store(self.tmp / "data")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def add(self, lid, trigger="slow tests after a fix", action="rerun only failing tests", bad="", reinforce=0):
        self.store.append("lesson_op", {"op": "add", "lesson_id": lid, "trigger": trigger, "action": action,
                                        "why": "w", "bad_action": bad})
        for _ in range(reinforce):
            self.store.append("lesson_op", {"op": "reinforce", "lesson_id": lid})


# ---------------------------------------------------------------- launcher logic
class ClaudeCheck(unittest.TestCase):
    def fake_run(self, stdout):
        return lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=stdout, stderr="")

    def test_not_installed(self):
        s = claude_cli.check(which=lambda: None)
        self.assertFalse(s.installed)

    def test_logged_in_and_out(self):
        s = claude_cli.check(run=self.fake_run('{"loggedIn": true}'), which=lambda: "/bin/claude")
        self.assertTrue(s.logged_in)
        s = claude_cli.check(run=self.fake_run('{"loggedIn": false}'), which=lambda: "/bin/claude")
        self.assertIs(s.logged_in, False)

    def test_unreadable_status_is_unknown_not_false(self):
        # An old CLI or a timeout must not be reported as "logged out": unknown is a different fact.
        s = claude_cli.check(run=self.fake_run("not json"), which=lambda: "/bin/claude")
        self.assertTrue(s.installed)
        self.assertIsNone(s.logged_in)

        def boom(*a, **k):
            raise subprocess.TimeoutExpired("claude", 20)
        self.assertIsNone(claude_cli.check(run=boom, which=lambda: "/bin/claude").logged_in)


class TerminalPlan(unittest.TestCase):
    def test_windows_has_no_fragile_quotes(self):
        # A quoted install path ("C:\Program Files\...") got re-escaped by Python as \" and broke cmd.exe.
        # The plan uses bare `claude` (found on PATH by check()), and the folder goes in cwd, never the command.
        plan = claude_cli.terminal_plan("Windows", r"C:\My Projects\app", r"C:\Program Files\claude.exe", chrome=True)
        self.assertEqual(plan["argv"], ["cmd", "/k", "claude --chrome"])
        self.assertNotIn('"', subprocess.list2cmdline(plan["argv"]).replace('"claude --chrome"', ""))
        self.assertEqual(plan["cwd"], r"C:\My Projects\app")
        self.assertTrue(plan["new_console"])

    def test_plain_button_has_no_chrome_flag(self):
        plan = claude_cli.terminal_plan("Windows", "C:\\x", "claude", chrome=False)
        self.assertNotIn("--chrome", plan["argv"][2])

    def test_mac_escapes_quotes_for_applescript(self):
        plan = claude_cli.terminal_plan("Darwin", '/Users/me/my "app"', "/usr/local/bin/claude", chrome=False)
        osa = plan["argv"][2]
        self.assertEqual(plan["argv"][:2], ["osascript", "-e"])
        self.assertIn('do script "cd ', osa)
        # every double quote inside the AppleScript string is escaped, so the folder name can't end it early
        inner = osa.split('do script "', 1)[1].rsplit('"\nend tell', 1)[0]
        self.assertNotRegex(inner, r'(?<!\\)"')

    def test_linux_gnome_uses_double_dash_and_none_without_terminal(self):
        plan = claude_cli.terminal_plan("Linux", "/home/me", "claude", True,
                                        which=lambda t: t == "gnome-terminal")
        self.assertEqual(plan["argv"][:2], ["gnome-terminal", "--"])
        self.assertIsNone(claude_cli.terminal_plan("Linux", "/home/me", "claude", True, which=lambda t: None))

    def test_launch_without_claude_shows_install_help_and_starts_nothing(self):
        with mock.patch("subprocess.Popen") as popen:
            ok, msg = claude_cli.launch("/tmp", False, status=claude_cli.Status(False), system="Windows")
        self.assertFalse(ok)
        self.assertIn("install.ps1", msg)
        popen.assert_not_called()


# ---------------------------------------------------------------- engine
class StoreTests(TmpStore):
    def test_roundtrip_with_non_ascii(self):
        self.store.append("observation", {"text": "ships fast → then polishes 🚀"})
        self.assertEqual(self.store.events()[0]["data"]["text"], "ships fast → then polishes 🚀")

    def test_unknown_type_rejected(self):
        with self.assertRaises(ValueError):
            self.store.append("nonsense", {})

    def test_corrupt_line_is_reported_not_skipped(self):
        self.store.append("observation", {"text": "ok"})
        with open(self.store.file, "a", encoding="utf-8") as f:
            f.write("{broken\n")
        with self.assertRaises(ValueError):
            self.store.events()

    def test_redact(self):
        self.assertEqual(redact("mail a@b.com key sk-" + "x" * 20), "mail [email] key [secret]")


class LessonTests(TmpStore):
    def test_trial_promotes_after_two_reinforcements(self):
        self.add("a", reinforce=1)
        self.assertEqual(L.lessons(self.store)["a"]["status"], "trial")
        self.store.append("lesson_op", {"op": "reinforce", "lesson_id": "a"})
        self.assertEqual(L.lessons(self.store)["a"]["status"], "active")

    def test_harmful_and_retired_lessons_are_hidden(self):
        self.add("harm", reinforce=1)
        self.store.append("lesson_op", {"op": "harmful", "lesson_id": "harm"})
        self.add("old")
        self.store.append("lesson_op", {"op": "retire", "lesson_id": "old"})
        self.assertEqual(L.relevant(self.store, "slow tests after a fix"), [])
        self.assertNotIn("[harm]", L.playbook(self.store))
        self.assertNotIn("[old]", L.playbook(self.store))

    def test_relevant_picks_matching_lessons_only(self):
        self.add("tests", trigger="slow tests after a fix", action="rerun only failing tests")
        self.add("css", trigger="styling a button", action="use the design tokens")
        self.assertEqual([l["id"] for l in L.relevant(self.store, "my slow tests failed")], ["tests"])

    def test_op_for_unknown_lesson_is_ignored(self):
        self.store.append("lesson_op", {"op": "reinforce", "lesson_id": "ghost"})
        self.assertEqual(L.lessons(self.store), {})


class EvalTests(TmpStore):
    def test_grade_counts_both_kinds_of_checks(self):
        case = evals.Case("c", "p", must_include=["failing"], must_not_include=["full suite"])
        self.assertEqual(evals.grade(case, "rerun the failing test"), 1.0)
        self.assertEqual(evals.grade(case, "rerun the full suite"), 0.0)

    def test_any_of_phrasings_count(self):
        # Correct answers worded differently must not score 0 (the first live run did exactly that).
        case = evals.Case("c", "p", must_include=[["failing", "failed", "--lf"]])
        self.assertEqual(evals.grade(case, "rerun the test that failed"), 1.0)
        self.assertEqual(evals.grade(case, "pytest --lf"), 1.0)
        self.assertEqual(evals.grade(case, "run everything"), 0.0)

    def test_zero_results_is_failure(self):
        with self.assertRaises(ValueError):
            evals.summarize([])

    def test_ab_lift_and_records(self):
        self.add("tests")
        lesson = L.lessons(self.store)["tests"]
        cases = [evals.Case("c", "what next?", must_include=["failing"])]
        model = lambda prompt, system: "rerun the failing tests" if "tests" in system else "run everything"
        res = evals.run_ab(self.store, lesson, cases, model)
        self.assertEqual((res["without"], res["with"], res["verdict"]), (0.0, 1.0, "helps"))
        self.assertEqual(len(self.store.events("eval_run")), 2)


class CouncilTests(TmpStore):
    def ask(self, fail=()):
        def ask(prompt):
            for role in fail:
                if prompt.startswith("You are the %s" % role.upper()):
                    raise RuntimeError("down")
            return "Ranking: 1, 2, 3" if prompt.startswith("You are a blind") else "answer"
        return ask

    def test_outsider_gets_no_context(self):
        self.assertNotIn("SECRET-CONTEXT", council.advisor_prompt("outsider", "q", "SECRET-CONTEXT"))
        self.assertIn("SECRET-CONTEXT", council.advisor_prompt("contrarian", "q", "SECRET-CONTEXT"))

    def test_review_is_blind(self):
        answers = {r: "text from %s" % r for r in council.ROLES}
        numbered, key = council.blind({r: "x" for r in council.ROLES}, random.Random(1))
        prompt = council.review_prompt("q", numbered)
        for role in council.ROLES:
            self.assertNotIn(role.upper(), prompt)
        self.assertEqual(sorted(key.values()), sorted(answers))

    def test_missing_advisors_are_reported(self):
        res = council.run("q", self.ask(fail=("contrarian",)), parallel=False)
        self.assertEqual(res["missing"], ["contrarian"])
        with self.assertRaises(RuntimeError):   # fewer than 3 answers: no verdict
            council.run("q", self.ask(fail=("contrarian", "outsider", "executor")), parallel=False)

    def test_record_refuses_invented_follow(self):
        res = council.run("q", self.ask(), parallel=False)
        with self.assertRaises(ValueError):
            council.record(self.store, res, decision="", followed_verdict=True)
        council.record(self.store, res, decision="I'll go with B", followed_verdict=True)
        self.assertEqual(self.store.events("council")[0]["data"]["decision"], "I'll go with B")


class ExportTests(TmpStore):
    def test_export_files_pairs_and_redaction(self):
        self.add("a", action="email me at a@b.com", bad="ignore it")
        self.add("b")   # no bad_action: no preference pair can be made honestly
        m = export.export(self.store, self.tmp / "out")
        self.assertEqual(m["counts"]["sft.jsonl"], 2)
        self.assertEqual(m["counts"]["preference_pairs.jsonl"], 1)
        text = (self.tmp / "out" / "sft.jsonl").read_text(encoding="utf-8")
        self.assertNotIn("a@b.com", text)
        self.assertIn("[email]", text)


class HookTests(TmpStore):
    def test_session_start_shows_only_active(self):
        self.add("active-one", reinforce=2)
        self.add("trial-one")
        ctx = hooks.session_start(self.store)
        self.assertIn("active-one", ctx)
        self.assertNotIn("trial-one", ctx)

    def test_hook_output_format(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            hooks.respond("UserPromptSubmit", "hello")
        out = json.loads(buf.getvalue())
        self.assertEqual(out["hookSpecificOutput"]["additionalContext"], "hello")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            hooks.respond("UserPromptSubmit", "")
        self.assertEqual(buf.getvalue(), "")   # nothing relevant → print nothing, add no noise


# ---------------------------------------------------------------- end to end
class EndToEnd(unittest.TestCase):
    def test_demo_runs_the_whole_loop(self):
        res = demo.run(out=lambda *a: None)
        try:
            self.assertEqual(res["eval"]["verdict"], "helps")
            self.assertEqual(res["manifest"]["counts"]["council.jsonl"], 1)
            self.assertTrue((res["dir"] / "export" / "manifest.json").exists())
        finally:
            shutil.rmtree(res["dir"], ignore_errors=True)

    def test_cli_lesson_add_then_playbook(self):
        tmp = tempfile.mkdtemp(prefix="raga-cli-")
        env = dict(os.environ, RAGA_HOME=tmp, PYTHONIOENCODING="utf-8")
        run = lambda *a: subprocess.run([sys.executable, str(ROOT / "raga.py")] + list(a), capture_output=True,
                                        text=True, encoding="utf-8", env=env)
        try:
            out = run("lesson", "add", "--trigger", "deploying on a Friday", "--action", "wait until Monday")
            self.assertIn("added deploying-on-a-friday", out.stdout, out.stderr)
            self.assertIn("wait until Monday", run("playbook").stdout)
            self.assertNotEqual(run("lesson", "reinforce", "nope").returncode, 0)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
