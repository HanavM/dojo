"""Stage 5: held-out evaluation of A (no notes) vs B (self-notes) vs C (Dojo).

Held-out seeds 100-104, never touched during practice.

CybORG leans on the global RNG, so every episode runs in its own PROCESS --
threads would interleave the RNG and destroy reproducibility.
"""
import json
import os
import statistics
import sys
import time
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, "/Users/hanavmodasiya/trainme")
sys.path.insert(0, "/Users/hanavmodasiya/trainme/cage")

RESULTS = "/Users/hanavmodasiya/trainme/results/results.json"
EVAL_SEEDS = [100, 101, 102, 103, 104]
PRACTICE_SEEDS = [1, 2, 3, 4, 5, 6]     # same seeds B and C practise on
PRACTICE_STEPS = 30
EVAL_STEPS = 30

TASK = ("Defend a CAGE Challenge 2 network for 30 steps against a Meander red "
        "agent, which spreads broadly across hosts instead of beelining to the "
        "operational server.")


# -- condition B: self-notes, no teacher ----------------------------------
SELF_REFLECT_SYSTEM = """You just played one episode as the Blue defender in CAGE
Challenge 2 and you are writing notes to yourself to do better next time.

Scoring: negative penalties summed, 0 is perfect. You are not told the exact
penalty table -- infer what you can from the rewards you received.

Write 3-5 lessons. Each is ONE short imperative sentence you could act on at a
future step. Reply as strict JSON only: {"lessons": ["...", "..."]}"""

SELF_CONSOLIDATE_SYSTEM = """Rewrite your accumulated notes into 6-10 durable rules
that will generalise to unseen episodes. Drop step numbers, merge duplicates,
put the highest-value rule first, one imperative sentence each.
Reply as strict JSON only: {"lessons": ["...", "..."]}"""


def _self_reflect(trajectory, score, prior, final_obs):
    from dojo.llm import chat, STUDENT_MODEL
    from dojo.teacher import _json_from

    rows = "\n".join(
        f"  step {t['step']:2d}: {t['action']:<24} reward {t['reward']:6.1f}"
        for t in trajectory
    )
    prior_txt = ("\nNotes you already wrote (build on them, do not repeat):\n"
                 + "\n".join(f"- {x}" for x in prior)) if prior else ""
    user = (f"Task: {TASK}\nFinal score: {score:.1f}\n\n"
            f"What you did:\n{rows}\n\nNetwork state at the end:\n{final_obs}{prior_txt}")
    try:
        raw = chat(STUDENT_MODEL, SELF_REFLECT_SYSTEM, user, max_tokens=600,
                   temperature=0.3, tag="self:reflect")
    except Exception:
        return []
    data = _json_from(raw) or {}
    return [str(x).strip() for x in data.get("lessons", []) if str(x).strip()][:5]


def learn_self():
    """Condition B: same practice budget, own reflections, no teacher."""
    from dojo.agent import BlueAgent
    from dojo.runner import run_episode
    from dojo.llm import chat, STUDENT_MODEL
    from dojo.teacher import _json_from

    lessons, curve = [], []
    for i, seed in enumerate(PRACTICE_SEEDS):
        blob = "\n".join(f"- {l}" for l in lessons)
        agent = BlueAgent(notes=blob, name="selfnotes")
        ep = run_episode(agent, seed=seed, max_steps=PRACTICE_STEPS, tag="selfpractice")
        curve.append({"episode": i + 1, "seed": seed, "scaffold_level": None,
                      "score": ep["score"]})
        final_obs = ep["trajectory"][-1]["obs"] if ep["trajectory"] else ""
        for l in _self_reflect(ep["trajectory"], ep["score"], lessons, final_obs):
            if l not in lessons:
                lessons.append(l)
        print(f"  [B] practice {i+1}: seed={seed} score={ep['score']:.1f} "
              f"({len(lessons)} notes)", flush=True)

    if len(lessons) >= 3:
        try:
            raw = chat(STUDENT_MODEL, SELF_CONSOLIDATE_SYSTEM,
                       "Your notes:\n" + "\n".join(f"- {x}" for x in lessons),
                       max_tokens=900, temperature=0.2, tag="self:consolidate")
            got = [str(x).strip() for x in (_json_from(raw) or {}).get("lessons", [])
                   if str(x).strip()]
            if got:
                lessons = got
        except Exception:
            pass
    return {"lessons": lessons, "practice_curve": curve, "spend_usd": 0.0}


def learn_dojo():
    """Condition C: buy a Dojo session and use the teacher's lesson pack."""
    from dojo.student_client import buy_and_learn
    return buy_and_learn(TASK, verbose=True)


# -- held-out evaluation --------------------------------------------------
def _eval_one(args):
    """Runs in its own process: one condition, one held-out seed."""
    cond, notes, seed = args
    from dojo.agent import BlueAgent
    from dojo.runner import run_episode

    agent = BlueAgent(notes=notes, name=f"eval{cond}")
    ep = run_episode(agent, seed=seed, max_steps=EVAL_STEPS,
                     allow_eval_seed=True, tag=f"eval{cond}")
    return {
        "condition": cond, "seed": seed, "score": ep["score"],
        "invalid_picks": ep["invalid_picks"],
        "actions": [t["action"] for t in ep["trajectory"]],
    }


def main():
    t0 = time.time()
    os.makedirs(os.path.dirname(RESULTS), exist_ok=True)

    # --- practice: B and C in parallel -----------------------------------
    print("=== practice phase (B self-notes and C dojo, in parallel) ===", flush=True)
    with ProcessPoolExecutor(max_workers=2) as pool:
        f_dojo = pool.submit(learn_dojo)
        f_self = pool.submit(learn_self)
        dojo_out = f_dojo.result()
        self_out = f_self.result()

    notes = {
        "A": "",
        "B": "\n".join(f"- {l}" for l in self_out["lessons"]),
        "C": "\n".join(f"- {l}" for l in dojo_out["lessons"]),
    }
    for cond in ("B", "C"):
        path = f"/Users/hanavmodasiya/trainme/notes/notes_{cond}.md"
        with open(path, "w") as f:
            f.write(f"# Notes ({cond})\n\n{notes[cond]}\n")
    with open("/Users/hanavmodasiya/trainme/notes/notes.md", "w") as f:
        f.write(f"# Dojo lessons\n\n{notes['C']}\n")

    # --- held-out eval: 3 conditions x 5 seeds, in parallel ---------------
    print(f"\n=== held-out eval on seeds {EVAL_SEEDS} ===", flush=True)
    jobs = [(c, notes[c], s) for c in ("A", "B", "C") for s in EVAL_SEEDS]
    episodes = []
    with ProcessPoolExecutor(max_workers=5) as pool:
        for r in pool.map(_eval_one, jobs):
            episodes.append(r)
            print(f"  [{r['condition']}] seed {r['seed']}: {r['score']:.1f}", flush=True)

    # --- aggregate --------------------------------------------------------
    summary = {}
    for cond in ("A", "B", "C"):
        scores = [e["score"] for e in episodes if e["condition"] == cond]
        summary[cond] = {
            "scores": [round(s, 2) for s in scores],
            "mean": round(statistics.mean(scores), 3),
            "std": round(statistics.pstdev(scores), 3) if len(scores) > 1 else 0.0,
            "n": len(scores),
        }

    from dojo import payments
    results = {
        "generated": time.time(),
        "benchmark": "CAGE Challenge 2 (CybORG 2.1), Scenario2, Meander red, 30 steps",
        "caveat": "Small-sample comparison: n=5 held-out seeds per condition.",
        "eval_seeds": EVAL_SEEDS,
        "practice_seeds": PRACTICE_SEEDS,
        "models": {
            "student": os.environ.get("DOJO_STUDENT_MODEL", "gpt-4o-mini"),
            "teacher": os.environ.get("DOJO_TEACHER_MODEL", "gpt-4o"),
            "provider": "Azure AI Foundry",
        },
        "conditions": {
            "A": {"label": "No notes", "desc": "agent plays cold"},
            "B": {"label": "Self-notes",
                  "desc": f"{len(PRACTICE_SEEDS)} practice episodes, own reflections, no teacher"},
            "C": {"label": "Dojo (paid teacher)",
                  "desc": "paid learning session with fading scaffolds and teacher critique"},
        },
        "summary": summary,
        "episodes": episodes,
        "practice_curves": {"B": self_out["practice_curve"], "C": dojo_out["practice_curve"]},
        "lessons": {"B": self_out["lessons"], "C": dojo_out["lessons"]},
        "dojo_session_id": dojo_out.get("session_id"),
        "replay": dojo_out.get("replay"),
        "spend": {
            "dojo_session_usd": dojo_out.get("spend_usd", 0.0),
            "total_ledger_usd": payments.total_spend(),
            "mode": payments.MODE,
            "entries": payments.entries(),
        },
        "elapsed_s": round(time.time() - t0, 1),
    }
    tmp = RESULTS + ".tmp"
    with open(tmp, "w") as f:
        json.dump(results, f, indent=2)
    os.replace(tmp, RESULTS)

    print("\n=== RESULTS (mean score, 0 is perfect, higher is better) ===")
    for cond in ("A", "B", "C"):
        s = summary[cond]
        print(f"  {cond} {results['conditions'][cond]['label']:<22} "
              f"mean={s['mean']:8.2f}  std={s['std']:6.2f}  {s['scores']}")
    print(f"\nspend: ${results['spend']['total_ledger_usd']:.2f} "
          f"({results['spend']['mode']})   elapsed {results['elapsed_s']}s")
    print(f"written to {RESULTS}")


if __name__ == "__main__":
    main()
