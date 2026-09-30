"""The buyer: an agent that pays for a Dojo session and learns from it.

This is the demo of the whole pitch -- an agent meets an unfamiliar task,
buys a teacher, practises with fading help, and walks away with notes.
"""
import json
import os
import sys

import httpx

sys.path.insert(0, "/Users/hanavmodasiya/trainme")

from dojo import payments
from dojo.agent import BlueAgent
from dojo.runner import run_episode

BASE_URL = os.environ.get("DOJO_URL", "http://127.0.0.1:8000")
NOTES_PATH = "/Users/hanavmodasiya/trainme/notes/notes.md"


def _pay_and_post(client, path, payload):
    """Paid route: attach payment, retry once if the gate wants it."""
    headers = payments.pay_headers(path)
    r = client.post(BASE_URL + path, json=payload, headers=headers, timeout=180)
    return r


def buy_and_learn(task_description, base_url=None, verbose=True, notes=""):
    global BASE_URL
    if base_url:
        BASE_URL = base_url
    spend_before = payments.total_spend()

    with httpx.Client() as client:
        r = _pay_and_post(client, "/learn/start", {"task_description": task_description})
        if r.status_code != 200:
            raise RuntimeError(f"/learn/start failed [{r.status_code}]: {r.text[:300]}")
        start = r.json()
        sid = start["session_id"]
        level = start["scaffold_level"]
        practice = start["practice"]
        if verbose:
            print(f"[paid ${payments.price_of('/learn/start'):.2f}] session {sid} "
                  f"-- scaffold {level}: {start['scaffold_desc']}")

        lessons_so_far = list(notes.splitlines()) if notes else []
        curve = []
        final_pack = []
        replay = None

        while True:
            # The student plays with whatever notes it has so far.
            note_blob = "\n".join(f"- {l}" for l in lessons_so_far if l.strip())
            agent = BlueAgent(notes=note_blob, name="student")

            def hint_fn(step, obs, history, env, _sid=sid, _level=level):
                if _level <= 1:
                    return None
                recent = [f"step {h['step']}: {h['action']} (reward {h['reward']:.1f})"
                          for h in history[-5:]]
                try:
                    hr = client.post(BASE_URL + "/learn/hint", timeout=120, json={
                        "session_id": _sid, "step": step, "obs": obs,
                        "recent_actions": recent,
                    })
                    return hr.json().get("hint")
                except Exception:
                    return None   # a dropped hint must not kill the episode

            ep = run_episode(agent, seed=practice["seed"],
                             hint_fn=hint_fn if level >= 2 else None,
                             max_steps=practice["steps"], red=practice["red"],
                             tag=f"dojo:{sid}")
            if verbose:
                print(f"  practice {len(curve)+1}: seed={practice['seed']} "
                      f"scaffold={level} score={ep['score']:.1f}")

            curve.append({"episode": len(curve) + 1, "seed": practice["seed"],
                          "scaffold_level": level, "score": ep["score"]})
            if replay is None:
                replay = {"session_id": sid, "seed": practice["seed"],
                          "scaffold_level": level, "score": ep["score"],
                          "trajectory": ep["trajectory"]}

            sr = client.post(BASE_URL + "/learn/submit", timeout=300, json={
                "session_id": sid,
                "trajectory": [{k: v for k, v in t.items() if k != "obs"}
                               | ({"obs": t["obs"]} if t["step"] == ep["steps"] else {})
                               for t in ep["trajectory"]],
                "score": ep["score"],
            })
            if sr.status_code != 200:
                raise RuntimeError(f"/learn/submit failed [{sr.status_code}]: {sr.text[:300]}")
            out = sr.json()
            for l in out.get("lessons", []):
                if l not in lessons_so_far:
                    lessons_so_far.append(l)
            if verbose:
                for l in out.get("lessons", []):
                    print(f"     lesson: {l}")

            if out.get("done"):
                final_pack = out.get("final_lesson_pack", lessons_so_far)
                if verbose:
                    print(f"  session complete -- {out.get('reason')}")
                break
            level = out["scaffold_level"]
            practice = out["practice"]

    spend = round(payments.total_spend() - spend_before, 6)
    return {"session_id": sid, "lessons": final_pack or lessons_so_far,
            "practice_curve": curve, "spend_usd": spend, "replay": replay}


def write_notes(lessons, path=NOTES_PATH, header="Dojo lessons"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    body = "\n".join(f"- {l}" for l in lessons)
    with open(path, "w") as f:
        f.write(f"# {header}\n\n{body}\n")
    return path


if __name__ == "__main__":
    task = ("Defend a CAGE Challenge 2 network for 30 steps against a Meander "
            "red agent, which spreads broadly instead of beelining.")
    out = buy_and_learn(task)
    write_notes(out["lessons"])
    print(json.dumps({k: v for k, v in out.items() if k != "replay"}, indent=2)[:2000])
