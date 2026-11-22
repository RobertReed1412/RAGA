"""Lessons: "when <situation> → do <better action>, because <why>", learned from real sessions.

A lesson's state is never stored directly. It is rebuilt by replaying its `lesson_op` events:
  add        a new lesson starts as "trial"
  reinforce  it helped again (2 reinforcements promote trial → active)
  harmful    it made things worse (counts double against it)
  retire     no longer true; kept in history, never shown again
Only active and trial lessons reach the agent, and only the relevant ones (see `relevant`).
"""
import re

PROMOTE_AT = 2   # reinforcements needed before a trial lesson is trusted as active
STOP = set("a an the and or but if then when this that with from have what your will just they them into "
           "about would could should there their make made need want like also some more only very each "
           "over such been were being does done doing here using used able after before while which where "
           "to of in on for is it be as at by do i you me my we".split())


def words(text):
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2 and w not in STOP}


def lessons(store):
    state = {}
    for ev in store.events("lesson_op"):
        d = ev["data"]
        lid, op = d.get("lesson_id"), d.get("op")
        if op == "add":
            state[lid] = {"id": lid, "trigger": d["trigger"], "action": d["action"], "why": d.get("why", ""),
                          "bad_action": d.get("bad_action", ""), "kind": d.get("kind", "fix"),
                          "domain": d.get("domain", "general"), "status": "trial",
                          "reinforced": 0, "harmful": 0, "history": []}
        if lid not in state:
            continue   # an op for a lesson we never saw added: ignore rather than invent one
        lesson = state[lid]
        lesson["history"].append({"op": op, "ts": ev["ts"], "evidence": d.get("evidence", "")})
        if op == "reinforce":
            lesson["reinforced"] += 1
            if lesson["status"] == "trial" and lesson["reinforced"] >= PROMOTE_AT:
                lesson["status"] = "active"
        elif op == "harmful":
            lesson["harmful"] += 1
        elif op == "retire":
            lesson["status"] = "retired"
    return state


def score(lesson):
    return lesson["reinforced"] - 2 * lesson["harmful"]   # one harm outweighs one help: safety first


def relevant(store, message, k=4):
    """The k live lessons that share the most words with this message.

    Why keyword overlap and not embeddings: zero dependencies, instant, and fully explainable (you can
    see exactly which words matched). With dozens of lessons it is good enough; embeddings are the
    upgrade path once the playbook grows into the hundreds.
    """
    msg = words(message)
    scored = []
    for lesson in lessons(store).values():
        if lesson["status"] not in ("trial", "active") or score(lesson) < 0:
            continue
        overlap = len(msg & words(lesson["trigger"] + " " + lesson["action"]))
        if overlap:
            scored.append((overlap, score(lesson), lesson))
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return [t[2] for t in scored[:k]]


def line(lesson):
    return "- **[%s]** When %s → %s (why: %s)" % (lesson["id"], lesson["trigger"], lesson["action"], lesson["why"])


def playbook(store):
    live = [l for l in lessons(store).values() if l["status"] in ("trial", "active") and score(l) >= 0]
    live.sort(key=score, reverse=True)
    out = ["# Playbook", ""]
    for status in ("active", "trial"):
        group = [l for l in live if l["status"] == status]
        if group:
            out.append("## %s" % status.title())
            out += [line(l) for l in group] + [""]
    return "\n".join(out)
