"""Export what RAGA learned as training data for a future model of your own.

  sft.jsonl               chat examples: situation → the better action (supervised fine-tuning)
  preference_pairs.jsonl  prompt / chosen / rejected (DPO-style preference training)
  eval_runs.jsonl         every A/B eval answer and score: proof of which lessons help
  council.jsonl           decisions: what the council said next to what the person actually chose
  manifest.json           schema version, counts, and what each file is

Why export at all: today the lessons live in the prompt (cheap, reversible). Later, the same data can
fine-tune an open model so it starts out already knowing them. Everything passes through `redact`.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from .lessons import lessons
from .store import SCHEMA, redact

SYSTEM = "You are RAGA, a personal AI that learns from experience and applies it."
DESCRIPTIONS = {
    "sft.jsonl": "chat examples: situation -> better action (supervised fine-tuning)",
    "preference_pairs.jsonl": "prompt/chosen/rejected pairs (DPO-style preference training)",
    "eval_runs.jsonl": "A/B eval answers and scores: evidence of which lessons help",
    "council.jsonl": "council verdicts next to the decision the person actually made",
}


def build(store):
    live = [l for l in lessons(store).values() if l["status"] in ("trial", "active")]
    sft = [{"messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": "Situation: %s. What should I do?" % l["trigger"]},
                         {"role": "assistant", "content": "%s. Why: %s" % (l["action"], l["why"])}]}
           for l in live]
    pairs = [{"prompt": "Situation: %s. What should I do?" % l["trigger"],
              "chosen": l["action"], "rejected": l["bad_action"]}
             for l in live if l["bad_action"]]   # a pair needs a real "what was done instead"
    return {"sft.jsonl": sft, "preference_pairs.jsonl": pairs,
            "eval_runs.jsonl": [e["data"] for e in store.events("eval_run")],
            "council.jsonl": [e["data"] for e in store.events("council")]}


def export(store, out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    files = build(store)
    for name, rows in files.items():
        with open(out / name, "w", encoding="utf-8", newline="\n") as f:
            for row in rows:
                f.write(redact(json.dumps(row, ensure_ascii=False)) + "\n")
    manifest = {"schema": SCHEMA, "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "counts": {k: len(v) for k, v in files.items()},
                "files": DESCRIPTIONS}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return manifest
