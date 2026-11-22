"""A/B evals: does a lesson actually make the model's answers better?

Each case runs twice on the same prompt:
  without  the model answers with no lesson
  with     the lesson is added to the system prompt
Rule-based graders score both answers (0..1), and lift = mean(with) - mean(without).
A lesson that doesn't lift scores is noise in the prompt, and noise costs tokens and attention.

`model` is any function (prompt, system) -> answer. Tests and the demo pass a scripted stand-in;
`ClaudeModel` runs the real thing through `claude -p` (headless Claude Code).
"""
import shutil
import subprocess
from dataclasses import dataclass, field
from statistics import mean

from .lessons import line


@dataclass
class Case:
    id: str
    prompt: str
    # Each item is one check: a phrase, or a list of phrases where ANY one counts. The lists exist because
    # the first live run scored correct answers 0 ("failed" ≠ "failing"); see DECISIONS in the README.
    must_include: list = field(default_factory=list)
    must_not_include: list = field(default_factory=list)


def _found(item, text):
    return any(p.lower() in text for p in ([item] if isinstance(item, str) else item))


def grade(case, answer):
    """Fraction of checks passed. Deterministic on purpose: an LLM judge would add its own noise and bias."""
    text = answer.lower()
    checks = [_found(i, text) for i in case.must_include] + [not _found(i, text) for i in case.must_not_include]
    return sum(checks) / len(checks) if checks else 0.0


def run_ab(store, lesson, cases, model, record=True):
    rows = []
    for case in cases:
        for arm, system in (("without", ""), ("with", "Apply this lesson:\n" + line(lesson))):
            answer = model(case.prompt, system)
            row = {"case": case.id, "lesson_id": lesson["id"], "arm": arm, "score": grade(case, answer),
                   "answer": answer[:2000]}
            rows.append(row)
            if record:
                store.append("eval_run", row)
    return summarize(rows)


def summarize(rows):
    w = [r["score"] for r in rows if r["arm"] == "with"]
    wo = [r["score"] for r in rows if r["arm"] == "without"]
    if not w or not wo:
        # Zero results is a failure, not a pass: an eval that ran nothing proves nothing.
        raise ValueError("eval produced no results for one arm (with=%d, without=%d)" % (len(w), len(wo)))
    lift = mean(w) - mean(wo)
    return {"cases": len(w), "with": round(mean(w), 3), "without": round(mean(wo), 3), "lift": round(lift, 3),
            "verdict": "helps" if lift > 0 else ("hurts" if lift < 0 else "no effect")}


class ClaudeModel:
    """The real model: one `claude -p` call per answer. Needs Claude Code installed and logged in."""

    def __init__(self, model=None, timeout=180):
        self.path = shutil.which("claude")
        if not self.path:
            raise RuntimeError("Claude Code isn't installed: live mode needs the `claude` command.")
        self.model, self.timeout = model, timeout

    def __call__(self, prompt, system=""):
        argv = [self.path, "-p", prompt]
        if system:
            argv += ["--append-system-prompt", system]
        if self.model:
            argv += ["--model", self.model]
        out = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", timeout=self.timeout)
        if out.returncode != 0:
            raise RuntimeError("claude -p failed: %s" % (out.stderr.strip()[:300] or out.returncode))
        return out.stdout.strip()
