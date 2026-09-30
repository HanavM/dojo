"""The gauntlet loop: an agent paying, round by round, to be beaten harder.

Each iteration the world model builds a world aimed at this agent's weakness.
The same world is played on SEVERAL seeds by two agents:
  LEARNER  -- carries every note it has accumulated
  CONTROL  -- same model, same prompts, NO notes and NO memory of past rounds
The gap between them is what learning is worth, and it stays meaningful no
matter what the world model does to the environment.

Iteration 1 is run with empty notes on BOTH agents, so the gap it produces is
pure sampling noise -- that becomes the band every later gap is judged against.
"""
import json
import os
import statistics
import sys
from concurrent.futures import ProcessPoolExecutor

import httpx

sys.path.insert(0, "/Users/hanavmodasiya/trainme")
sys.path.insert(0, "/Users/hanavmodasiya/trainme/cage")

from worldenv import EnvConfig  # noqa: E402
from dojo import payments  # noqa: E402

BASE_URL = os.environ.get("DOJO_URL", "http://127.0.0.1:8000")
WORLD_SEEDS = [501, 502, 503]    # disjoint from practice (1-20) and eval (100-104)


def _play(args):
    """One episode, own process -- CybORG uses the global RNG."""
    cfg_dict, notes, seed, name, tag = args
    from dojo.agent import BlueAgent
    from dojo.runner import run_world_episode

    cfg = EnvConfig.from_dict(cfg_dict)
    agent = BlueAgent(notes=notes, name=name)
    r = run_world_episode(agent, cfg, seed, tag=tag)
    r["role"] = name
    return r


def _slim(result):
    """What the world model needs: score, action mix, final board."""
    return {
        "score": result["score"],
        "final_obs": result["final_obs"],
        "trajectory": [{"step": t["step"], "action": t["action"],
                        "reason": t["reason"], "reward": t["reward"]}
                       for t in result["trajectory"]],
    }


def run_gauntlet(task_description, iterations=4, seeds=None, verbose=True):
    seeds = seeds or WORLD_SEEDS
    spend_before = payments.total_spend()
    rounds, notes = [], []
    noise_band = None

    with httpx.Client(timeout=600) as client:
        hdrs = payments.pay_headers("/learn/start")
        r = client.post(BASE_URL + "/gauntlet/start", headers=hdrs,
                        json={"task_description": task_description, "notes": []})
        if r.status_code != 200:
            raise RuntimeError(f"/gauntlet/start [{r.status_code}]: {r.text[:300]}")
        out = r.json()
        sid, world = out["session_id"], out["world"]
        if verbose:
            print(f"[paid ${payments.price_of('/learn/start'):.2f}] gauntlet {sid}",
                  flush=True)

        for i in range(iterations):
            cfg_dict = world["config"]
            cfg = EnvConfig.from_dict(cfg_dict)
            note_blob = "\n".join(f"- {l}" for l in notes)
            if verbose:
                print(f"\n--- iteration {i+1} ---", flush=True)
                print(f"  world: {cfg.describe()}"
                      f"   [random floor {world.get('random_floor')}]", flush=True)
                if world.get("rejected_worlds"):
                    for rj in world["rejected_worlds"]:
                        print(f"  rejected: {rj['config_desc']} "
                              f"(floor {rj['floor']}) -- too easy", flush=True)
                if world.get("diagnosis"):
                    print(f"  diagnosis: {world['diagnosis']}", flush=True)

            jobs = ([(cfg_dict, note_blob, s, "learner", f"gauntlet:{sid}:learner")
                     for s in seeds]
                    + [(cfg_dict, "", s, "control", f"gauntlet:{sid}:control")
                       for s in seeds])
            with ProcessPoolExecutor(max_workers=min(6, len(jobs))) as pool:
                played = list(pool.map(_play, jobs))

            L = [p for p in played if p["role"] == "learner"]
            C = [p for p in played if p["role"] == "control"]
            lmean, cmean = statistics.mean(x["score"] for x in L), \
                           statistics.mean(x["score"] for x in C)
            lstd = statistics.pstdev([x["score"] for x in L]) if len(L) > 1 else 0.0
            cstd = statistics.pstdev([x["score"] for x in C]) if len(C) > 1 else 0.0
            gap = lmean - cmean

            # Iteration 1: both agents have empty notes, so this gap is noise.
            if i == 0:
                noise_band = abs(gap)

            verdict = ""
            if noise_band is not None and i > 0:
                verdict = ("above noise" if abs(gap) > noise_band
                           else "within noise -- unreadable")
            if verbose:
                print(f"  learner {lmean:7.1f} (sd {lstd:4.1f})   "
                      f"control {cmean:7.1f} (sd {cstd:4.1f})   "
                      f"gap {gap:+.1f}  {verdict}", flush=True)

            # Diagnose from the WORST episode -- that is where the failure mode
            # actually shows -- and store that exact episode so the replay and the
            # diagnosis are the same game.
            diag_L = min(L, key=lambda x: x["score"])
            diag_C = min(C, key=lambda x: x["score"])

            rounds.append({
                "iteration": i + 1, "config": cfg_dict, "config_desc": cfg.describe(),
                "seeds": seeds, "diagnosis": world.get("diagnosis", ""),
                "targeting": world.get("targeting", ""),
                "random_floor": world.get("random_floor"),
                "validated": world.get("validated"),
                "predicted_learner_score": world.get("predicted_learner_score"),
                "prediction_error": (
                    round(abs(world["predicted_learner_score"] - lmean), 2)
                    if world.get("predicted_learner_score") is not None else None),
                "rejected_worlds": world.get("rejected_worlds", []),
                "learner_scores": [x["score"] for x in L],
                "control_scores": [x["score"] for x in C],
                "learner_mean": lmean, "control_mean": cmean,
                "learner_std": lstd, "control_std": cstd,
                "gap": gap, "verdict": verdict,
                "is_noise_calibration": i == 0,
                "learner_trajectory": diag_L["trajectory"],
                "control_trajectory": next(
                    (x["trajectory"] for x in C if x["seed"] == diag_L["seed"]),
                    diag_C["trajectory"]),
                "diagnosed_seed": diag_L["seed"],
                "all_learner_trajectories": {str(x["seed"]): x["trajectory"] for x in L},
                "all_control_trajectories": {str(x["seed"]): x["trajectory"] for x in C},
                "round_lessons": [],   # filled in below, once the server replies
            })

            hdrs = payments.pay_headers("/gauntlet/next")
            r = client.post(BASE_URL + "/gauntlet/next", headers=hdrs, json={
                "session_id": sid,
                "learner": _slim(diag_L),
                "control": _slim(diag_C),
                "random_floor": world.get("random_floor"), "notes": notes})
            if r.status_code != 200:
                raise RuntimeError(f"/gauntlet/next [{r.status_code}]: {r.text[:300]}")
            nxt = r.json()
            rounds[-1]["round_lessons"] = list(nxt.get("lessons", []))
            for l in nxt.get("lessons", []):
                if l not in notes:
                    notes.append(l)
            if verbose:
                for l in nxt.get("lessons", []):
                    print(f"     lesson: {l}", flush=True)
            if nxt.get("done"):
                notes = nxt.get("final_lesson_pack", notes)
                break
            world = nxt["world"]

    return {"session_id": sid, "rounds": rounds, "notes": notes,
            "noise_band": noise_band,
            "gap_curve": [r["gap"] for r in rounds],
            "spend_usd": round(payments.total_spend() - spend_before, 6)}


if __name__ == "__main__":
    task = ("Defend a CAGE Challenge 2 network against an adaptive adversary that "
            "rewrites the network to exploit your weaknesses.")
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    out = run_gauntlet(task, iterations=n)
    print("\n=== gap curve (learner - control; bigger = notes worth more) ===",
          flush=True)
    print(f"noise band from iteration 1 (identical agents): +/- {out['noise_band']:.1f}")
    for r in out["rounds"]:
        tag = "  [noise calibration]" if r["is_noise_calibration"] else f"  {r['verdict']}"
        print(f"  iter {r['iteration']}: gap {r['gap']:+7.1f}   "
              f"{r['config_desc']}{tag}")
    print(f"\nspend ${out['spend_usd']:.2f}")
    path = os.environ.get("GAUNTLET_OUT",
                          "/Users/hanavmodasiya/trainme/results/gauntlet.json")
    with open(path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"written to {path}")
