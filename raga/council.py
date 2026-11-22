"""The LLM council: a second opinion that is built to disagree with you.

Why: a Stanford study in Science found AI models affirm users ~49% more often than humans do, and
people trust the flattering answers more. One model asked "is my plan good?" is a poor advisor.

How (after Karpathy's llm-council):
  1. Five advisors answer independently, each with one job, none seeing the others.
  2. Their answers are shuffled and numbered, with role names removed, and one reviewer ranks them.
     Hiding the roles makes the reviewer judge the reasoning, not who said it.
  3. A chairman writes one verdict and must keep the strongest dissent visible.

`ask` is any function prompt -> answer, so the same code runs with Claude (`ClaudeModel`) or with
scripted answers in tests and the demo.
"""
import random
from concurrent.futures import ThreadPoolExecutor

ROLES = {
    "contrarian": "Only say what will fail, and how.",
    "assumptions": "List every assumption the plan makes, then say which one is most likely wrong.",
    "expansionist": "Find the upside being missed. What does a bolder version look like?",
    "outsider": "You know nothing about this field. Ask the obvious questions an insider stops seeing.",
    "executor": "Only say what to do first: the 3 concrete next steps for each option.",
}
WORD_LIMIT = 150


def advisor_prompt(role, question, context=""):
    # The outsider deliberately gets no context: fresh eyes are the point of the role.
    ctx = "" if role == "outsider" or not context else "\nContext:\n%s\n" % context
    return ("You are the %s on an advisory council. %s\nAnswer in at most %d words and end with your pick.\n"
            "Decision: %s\n%s" % (role.upper(), ROLES[role], WORD_LIMIT, question, ctx))


def blind(answers, rng):
    """Shuffle answers and number them. Returns (numbered list, number → role) so ranks map back."""
    roles = list(answers)
    rng.shuffle(roles)
    numbered = [(i + 1, answers[r]) for i, r in enumerate(roles)]
    return numbered, {i + 1: r for i, r in enumerate(roles)}


def review_prompt(question, numbered):
    body = "\n\n".join("ANSWER %d:\n%s" % (n, a) for n, a in numbered)
    return ("You are a blind reviewer. Rank these anonymous answers by strength of reasoning and evidence, "
            "not length (reviewers tend to favor long answers; don't). Start your reply with the ranking "
            "as numbers, strongest first, like 'Ranking: 3, 1, 2'. Then name the weakest claim and the "
            "important point no one addressed.\nQuestion: %s\n\n%s" % (question, body))


def chairman_prompt(question, answers, review, missing):
    body = "\n\n".join("%s:\n%s" % (r.upper(), a) for r, a in answers.items())
    note = ("\nMissing advisors (failed to answer): %s. Say so and lower your confidence one step."
            % ", ".join(missing)) if missing else ""
    return ("You are the chairman. Give ONE verdict for: %s\nFormat: Verdict, Confidence (low/medium/high), "
            "Why (2-3 points), Strongest dissent (never smooth it over), What would change the answer, "
            "Next 3 steps.%s\n\nAdvisors:\n%s\n\nBlind review:\n%s" % (question, note, body, review))


def run(question, ask, context="", rng=None, parallel=True):
    rng = rng or random.Random()
    prompts = {r: advisor_prompt(r, question, context) for r in ROLES}

    def safe(role):
        try:
            return role, ask(prompts[role]).strip()
        except Exception:   # one failed advisor must not sink the council; it is reported as missing below
            return role, ""

    if parallel:
        with ThreadPoolExecutor(max_workers=len(ROLES)) as pool:
            results = dict(pool.map(safe, ROLES))
    else:
        results = dict(map(safe, ROLES))
    answers = {r: a for r, a in results.items() if a}
    missing = [r for r in ROLES if r not in answers]
    if len(answers) < 3:
        raise RuntimeError("only %d of 5 advisors answered (missing: %s); not enough for a verdict"
                           % (len(answers), ", ".join(missing)))
    numbered, key = blind(answers, rng)
    review = ask(review_prompt(question, numbered))
    verdict = ask(chairman_prompt(question, answers, review, missing))
    return {"question": question, "advisors": answers, "missing": missing, "blind_key": key,
            "review": review, "verdict": verdict}


def record(store, result, decision="", followed_verdict=None):
    """Save the run with the person's OWN call. An undecided row must not claim they followed the verdict."""
    if not decision.strip() and followed_verdict is not None:
        raise ValueError("followed_verdict must stay None until a decision is made")
    return store.append("council", {
        "question": result["question"],
        "advisors": {r: a[:300] for r, a in result["advisors"].items()},
        "missing": result["missing"], "verdict": result["verdict"][:2000],
        "decision": decision, "followed_verdict": followed_verdict})
