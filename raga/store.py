"""Append-only event store: every change RAGA learns is one JSON line, never edited or deleted.

Why event sourcing instead of a database or one big JSON file:
- History is never lost. A lesson's current state is rebuilt by replaying its ops, so you can see
  *why* it is active (who added it, which sessions reinforced it, when it was judged harmful).
- Plain JSONL merges cleanly in git, so several machines can share one brain.
- The same file is already training data: export just filters and reshapes it.
"""
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "raga.v1"   # versioned so future tooling can convert old data instead of dropping it
EVENT_TYPES = {"lesson_op", "eval_run", "council", "observation", "goal"}
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
SECRET_RE = re.compile(r"(sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,}|Bearer\s+[A-Za-z0-9._-]{16,})")


def redact(text):
    """Applied on export: the store is private, exports are meant to be shared or trained on."""
    return SECRET_RE.sub("[secret]", EMAIL_RE.sub("[email]", text))


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.file = self.root / "events.jsonl"

    def append(self, etype, data, source="agent"):
        if etype not in EVENT_TYPES:
            raise ValueError("unknown event type %r (allowed: %s)" % (etype, ", ".join(sorted(EVENT_TYPES))))
        ev = {"schema": SCHEMA, "id": uuid.uuid4().hex[:12],
              "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "type": etype, "source": source, "data": data}
        self.root.mkdir(parents=True, exist_ok=True)
        # Explicit utf-8 + "\n": Windows defaults to cp1252 and CRLF, which would crash on an emoji
        # and churn every line in git.
        with open(self.file, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
        return ev

    def events(self, etype=None):
        if not self.file.exists():
            return []
        out = []
        with open(self.file, encoding="utf-8") as f:
            for n, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except ValueError:
                    # A bad line is reported, not silently skipped: losing data quietly is the worst failure.
                    raise ValueError("%s line %d is not valid JSON" % (self.file, n))
                if etype is None or ev.get("type") == etype:
                    out.append(ev)
        return out
