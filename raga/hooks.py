"""Claude Code hooks: how lessons reach the agent without anyone remembering to paste them.

Claude Code runs a hook command at set moments and adds whatever it prints to the agent's context.
  session-start  → the top lessons (the playbook's core)
  prompt         → only the lessons that match what the user just typed (keeps the prompt small)

Why hooks and not a long system prompt: a hook runs every time, whatever the model "decides", and
retrieval means 50 lessons cost the same context as 4.
"""
import json
import sys

from . import lessons as L

CORE = 4


def session_start(store):
    live = [l for l in L.lessons(store).values() if l["status"] == "active" and L.score(l) >= 0]
    live.sort(key=L.score, reverse=True)
    if not live:
        return ""
    return "RAGA playbook (lessons from past sessions; apply them):\n" + "\n".join(L.line(l) for l in live[:CORE])


def prompt(store, message):
    hits = L.relevant(store, message)
    return ("RAGA lessons relevant to this message:\n" + "\n".join(L.line(l) for l in hits)) if hits else ""


def respond(event, context):
    """Claude Code's hook output format: JSON with hookSpecificOutput.additionalContext."""
    if context:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": context}}))


def main(store, which):
    payload = json.loads(sys.stdin.read() or "{}")
    if which == "session-start":
        respond("SessionStart", session_start(store))
    elif which == "prompt":
        respond("UserPromptSubmit", prompt(store, payload.get("prompt", "")))


SETTINGS_SNIPPET = """{
  "hooks": {
    "SessionStart": [{"hooks": [{"type": "command", "command": "python \\"%(raga)s\\" hook session-start"}]}],
    "UserPromptSubmit": [{"hooks": [{"type": "command", "command": "python \\"%(raga)s\\" hook prompt"}]}]
  }
}"""
