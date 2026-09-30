"""The final exam: does anything learned in the Dojo survive contact with a real task?

Four fixed, genuinely hard environments the agent has never trained on. The agent
has EVERY tool in all of them -- nothing is taken away. Held-out seeds.

Arms (all the same model, same prompts; only the notes file differs):
  none      -- no notes, no memory. The floor.
  gauntlet  -- notes earned against the adversarial world model
  teacher   -- notes from the teaching tier, if present (optional third arm)
"""
import json
import os
import statistics as st
import sys
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, "/Users/hanavmodasiya/trainme")
sys.path.insert(0, "/Users/hanavmodasiya/trainme/cage")

from worldenv import EnvConfig  # noqa: E402

OUT = "/Users/hanavmodasiya/trainme/results/final_exam.json"
EXAM_SEEDS = [700, 701, 702]          # disjoint from practice, eval and gauntlet

# Fixed exams. Chosen to be hard and varied, NOT tuned to any agent.
EXAMS = {
    "fast_attacker": dict(
        label="Fast attacker",
        blurb="An attacker that knows the network and drives straight at the crown jewels.",
        cfg=dict(red="bline", steps=30)),
    "long_siege": dict(
        label="Long siege",
        blurb="A sprawling attacker and 50 turns -- sustained pressure, no quick win.",
        cfg=dict(red="meander", steps=50)),
    "high_stakes": dict(
        label="High stakes",
        blurb="Fast attacker, and the operational machines are worth real points.",
        cfg=dict(red="bline", steps=30,
                 host_values={"Op_Host0": {"conf": "Medium"},
                              "Op_Host1": {"conf": "Medium"}})),
    "noisy_network": dict(
        label="Noisy network",
        blurb="Benign staff traffic that looks like reconnaissance, plus a long game.",
        cfg=dict(red="meander", steps=50, green_noise=True)),
}


def _play(args):
    exam_key, cfg_dict, notes, seed, arm = args
    from dojo.agent import BlueAgent
    from dojo.runner import run_world_episode

    cfg = EnvConfig.from_dict(cfg_dict)
    agent = BlueAgent(notes=notes, name=f"exam-{arm}")
    r = run_world_episode(agent, cfg, seed, tag=f"exam:{exam_key}:{arm}")
    return {"exam": exam_key, "arm": arm, "seed": seed, "score": r["score"],
            "steps": r["steps"],
            "actions": [t["action"] for t in r["trajectory"]]}


def load_arms(ablations=False):
    """The comparison is notes vs no notes. That is the whole question.

    `ablations=True` adds two extra arms that answer a DIFFERENT question --
    whether the world model's targeting mattered:
      blind   : notes earned against randomly chosen worlds
      teacher : notes from the plain teaching tier, no adversarial worlds
    """
    arms = {"no notes": ""}

    # Self-training: the agent's OWN notes, written without any teacher.
    st_path = "/Users/hanavmodasiya/trainme/results/selftrain.json"
    if os.path.exists(st_path):
        notes = json.load(open(st_path)).get("notes", [])
        if notes:
            arms["self notes"] = "\n".join(f"- {l}" for l in notes)

    # Teacher-written notes, for reference.
    g = "/Users/hanavmodasiya/trainme/results/gauntlet_llm.json"
    if os.path.exists(g):
        notes = json.load(open(g)).get("notes", [])
        if notes:
            arms["taught notes"] = "\n".join(f"- {l}" for l in notes)

    if ablations:
        b = "/Users/hanavmodasiya/trainme/results/gauntlet_random.json"
        if os.path.exists(b):
            notes = json.load(open(b)).get("notes", [])
            if notes:
                arms["blind"] = "\n".join(f"- {l}" for l in notes)
        r = "/Users/hanavmodasiya/trainme/results/results.json"
        if os.path.exists(r):
            notes = (json.load(open(r)).get("lessons") or {}).get("C", [])
            if notes:
                arms["teacher"] = "\n".join(f"- {l}" for l in notes)
    return arms


def main():
    arms = load_arms(ablations="--ablations" in sys.argv)
    print(f"arms: {', '.join(arms)}", flush=True)
    for k, v in arms.items():
        print(f"  {k:9s} {len(v.splitlines())} notes", flush=True)

    # Per-exam random floor: context for how hard each exam actually is.
    from dojo.runner import random_floor
    floors = {}
    for key, ex in EXAMS.items():
        floors[key] = round(random_floor(EnvConfig.from_dict(ex["cfg"]),
                                         seeds=(11, 12)), 1)
        print(f"  exam {key:15s} random floor {floors[key]:8.1f}", flush=True)

    jobs = [(key, ex["cfg"], notes, seed, arm)
            for key, ex in EXAMS.items()
            for arm, notes in arms.items()
            for seed in EXAM_SEEDS]
    print(f"\nrunning {len(jobs)} episodes...", flush=True)

    episodes = []
    with ProcessPoolExecutor(max_workers=6) as pool:
        for r in pool.map(_play, jobs):
            episodes.append(r)
            print(f"  [{r['exam']:<15} {r['arm']:<9}] seed {r['seed']}: "
                  f"{r['score']:8.1f}", flush=True)

    summary = {}
    for key in EXAMS:
        summary[key] = {}
        for arm in arms:
            s = [e["score"] for e in episodes
                 if e["exam"] == key and e["arm"] == arm]
            summary[key][arm] = {
                "scores": [round(x, 1) for x in s],
                "mean": round(st.mean(s), 2) if s else None,
                "worst": round(min(s), 2) if s else None,
                "blowups": sum(1 for x in s if x < -100),
            }

    overall = {}
    for arm in arms:
        s = [e["score"] for e in episodes if e["arm"] == arm]
        overall[arm] = {
            "mean": round(st.mean(s), 2), "median": round(st.median(s), 2),
            "worst": round(min(s), 2), "n": len(s),
            "blowups": sum(1 for x in s if x < -100),
        }

    out = {"exams": {k: {"label": v["label"], "blurb": v["blurb"],
                         "cfg": v["cfg"], "random_floor": floors[k]}
                     for k, v in EXAMS.items()},
           "seeds": EXAM_SEEDS, "arms": list(arms),
           "note": ("All arms are the same model with the same prompts and the "
                    "FULL action set. Only the notes file differs."),
           "summary": summary, "overall": overall, "episodes": episodes}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(out, f, indent=2)

    print("\n=== FINAL EXAM (damage taken; 0 is perfect, lower number is better) ===")
    hdr = f"{'exam':<16}" + "".join(f"{a:>14}" for a in arms)
    print(hdr)
    for key in EXAMS:
        row = f"{key:<16}"
        for arm in arms:
            m = summary[key][arm]["mean"]
            row += f"{m:>14.1f}" if m is not None else f"{'-':>14}"
        print(row)
    print("-" * len(hdr))
    print(f"{'OVERALL mean':<16}" + "".join(f"{overall[a]['mean']:>14.1f}" for a in arms))
    print(f"{'worst episode':<16}" + "".join(f"{overall[a]['worst']:>14.1f}" for a in arms))
    print(f"{'blowups(<-100)':<16}" + "".join(
        f"{str(overall[a]['blowups'])+'/'+str(overall[a]['n']):>14}" for a in arms))
    print(f"\nwritten to {OUT}")


if __name__ == "__main__":
    main()
