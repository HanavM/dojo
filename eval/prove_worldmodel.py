"""Is the 'world model' actually modelling anything, or just narrating?

An LLM writing "I diagnose X, so I will do Y" costs nothing and proves nothing.
Two tests it cannot pass by narration:

TEST 1 -- DISCRIMINATION. We hand it episodes from agents with weaknesses we
          PLANTED, so we know the ground truth. Does it name the right fault,
          and does it build a DIFFERENT world for a different fault? An LLM
          pattern-matching on the game description would say the same thing
          every time.

TEST 2 -- PREDICTION. Before the episode is played, it predicts the agent's
          score in the world it just built. Then we play it. A thing that can
          predict outcomes has a model; a thing that cannot, doesn't. Scored
          against a naive baseline that always guesses the random-agent floor.
"""
import json
import os
import re
import statistics as st
import sys

sys.path.insert(0, "/Users/hanavmodasiya/trainme")
sys.path.insert(0, "/Users/hanavmodasiya/trainme/cage")

from worldenv import EnvConfig  # noqa: E402
from dojo.world_model import next_world, world_headroom  # noqa: E402

OUT = "/Users/hanavmodasiya/trainme/results/worldmodel_proof.json"
HOSTS_U = ["User1", "User2", "User3", "User4"]
ENT = ["Enterprise0", "Enterprise1", "Enterprise2"]

# ---- planted agents. We construct these, so we KNOW what is wrong with them ----
def _traj(actions, rewards):
    cum, out = 0.0, []
    for i, (a, r) in enumerate(zip(actions, rewards), 1):
        cum += r
        out.append({"step": i, "action": a, "reason": "(synthetic)",
                    "reward": r, "cumulative": round(cum, 2)})
    return out


def profile_never_restores():
    """Alternates Analyse/Remove forever. Remove does not clear root, so it
    bleeds. Ground truth: UNDER-uses Restore."""
    acts, rews = [], []
    for i in range(15):
        h = ENT[i % 3]
        acts += [f"Analyse {h}", f"Remove {h}"]
        rews += [-(1.0 + i * 0.15)] * 2
    return acts[:30], rews[:30]


def profile_restore_spam():
    """Restores almost every turn on a clean network. Ground truth: OVER-uses
    Restore; paying the -1.0 cost for nothing."""
    acts = [f"Restore {(ENT + HOSTS_U)[i % 7]}" for i in range(28)] + ["Monitor"] * 2
    rews = [-1.0] * 28 + [0.0, 0.0]
    return acts, rews


def profile_passive():
    """Watches while the network burns. Ground truth: TOO PASSIVE, never acts."""
    acts = ["Monitor"] * 20 + ["Analyse User1"] * 10
    rews = [-(0.2 + i * 0.12) for i in range(30)]
    return acts, rews


PROFILES = {
    "never_restores": dict(
        fn=profile_never_restores,
        truth="under-uses Restore / relies on Remove which does not clear root",
        hit=[r"under.?us\w* restore", r"(fails?|neglect\w*|does not|doesn't|rarely|never)"
             r"[^.]{0,40}restor", r"remove[^.]{0,40}(privileg|root|does not|doesn't)",
             r"restore[^.]{0,30}(underus|insufficient|too few|not used)"],
        miss=[r"over.?us\w* restore", r"excessive\w*[^.]{0,20}restore"]),
    "restore_spam": dict(
        fn=profile_restore_spam,
        truth="over-uses Restore on an already-clean network",
        hit=[r"over.?us\w*[^.]{0,20}restore", r"excessiv\w*[^.]{0,25}restore",
             r"restore[^.]{0,40}(unnecessar|wast|even when|not compromis|clean)",
             r"(unnecessar|wast)\w*[^.]{0,25}restore"],
        miss=[r"under.?us\w* restore", r"(never|fails? to|neglect\w*)[^.]{0,25}restore"]),
    "passive": dict(
        fn=profile_passive,
        truth="too passive; monitors/analyses instead of acting",
        hit=[r"passiv", r"over.?us\w*[^.]{0,20}(monitor|analyse|analyz)",
             r"(monitor|analyse|analyz)\w*[^.]{0,40}(instead|without|fails?|does not|doesn't|never)",
             r"(inact|fails? to act|no.{0,10}action|does not take action)"],
        miss=[r"over.?us\w*[^.]{0,20}restore"]),
}


def _classify(diagnosis, prof):
    d = (diagnosis or "").lower()
    hit = any(re.search(p, d) for p in prof["hit"])
    miss = any(re.search(p, d) for p in prof["miss"])
    if hit and not miss:
        return "correct"
    if miss and not hit:
        return "opposite"
    if hit and miss:
        return "ambiguous"
    return "missed"


def fake_round(profile_key, score):
    acts, rews = PROFILES[profile_key]["fn"]()
    traj = _traj(acts, rews)
    final = ("| Enterprise1 | Exploit | Privileged |\n"
             "| Op_Server0  | Scan    | Unknown    |")
    return {"score": score, "final_obs": final, "trajectory": traj}


# ---------------------------------------------------------------- TEST 1
def test_discrimination(trials=3):
    print("=" * 74)
    print("TEST 1 -- DISCRIMINATION: can it name a fault we planted?")
    print("=" * 74)
    rows, worlds_by_profile = [], {}
    for key, prof in PROFILES.items():
        worlds_by_profile[key] = []
        print(f"\n  planted fault: {prof['truth']}")
        for t in range(trials):
            learner = fake_round(key, -60.0)
            control = fake_round("passive", -65.0)
            try:
                cfg, payload = next_world([], [], learner, control)
            except Exception as e:
                print(f"    trial {t+1}: ERROR {type(e).__name__}")
                continue
            verdict = _classify(payload["diagnosis"], prof)
            worlds_by_profile[key].append(cfg.describe())
            rows.append({"profile": key, "trial": t + 1,
                         "diagnosis": payload["diagnosis"],
                         "world": cfg.describe(), "verdict": verdict})
            print(f"    trial {t+1}: [{verdict:^9}] {payload['diagnosis'][:88]}")

    correct = sum(1 for r in rows if r["verdict"] == "correct")
    print(f"\n  diagnosis accuracy: {correct}/{len(rows)}"
          f"   (chance with 3 faults is about 1/3)")

    # Does it build DIFFERENT worlds for DIFFERENT faults?
    print("\n  worlds built per planted fault:")
    for k, v in worlds_by_profile.items():
        print(f"    {k:<16} {set(v)}")
    all_worlds = [w for v in worlds_by_profile.values() for w in v]
    distinct_overall = len(set(all_worlds))
    per_profile_modes = {k: (st.mode(v) if v else None)
                         for k, v in worlds_by_profile.items()}
    differentiates = len(set(m for m in per_profile_modes.values() if m)) > 1
    print(f"\n  distinct worlds overall: {distinct_overall}")
    print(f"  builds different worlds for different faults: {differentiates}")
    return {"rows": rows, "accuracy": f"{correct}/{len(rows)}",
            "accuracy_pct": round(100 * correct / max(1, len(rows)), 1),
            "worlds_by_profile": worlds_by_profile,
            "differentiates": differentiates,
            "distinct_worlds": distinct_overall}


# ---------------------------------------------------------------- TEST 2
PREDICT_SYS = """You built the world described below for a specific agent. Predict
how that agent will actually score in it.

Scoring: summed negative penalties over the episode, 0 is perfect. For context a
RANDOM agent scores about {floor} in this exact world.

Reply as strict JSON only: {{"predicted_score": <number>, "reasoning": "one line"}}"""


def test_prediction(n_worlds=4):
    """Make it predict, then actually play. Compare to a naive baseline."""
    from dojo.llm import chat, TEACHER_MODEL
    from dojo.agent import BlueAgent
    from dojo.runner import run_world_episode
    from dojo.world_model import _json_from

    print("\n" + "=" * 74)
    print("TEST 2 -- PREDICTION: can it forecast the score in the world it built?")
    print("=" * 74)

    worlds = [
        EnvConfig(red="meander", steps=30),
        EnvConfig(red="bline", steps=30),
        EnvConfig(red="meander", steps=30, green_noise=True),
        EnvConfig(red="bline", steps=30,
                  host_values={"Op_Host0": {"conf": "Medium"}}),
    ][:n_worlds]

    rows = []
    for cfg in worlds:
        floor, _, _ = world_headroom(cfg)
        user = (f"The world you built: {cfg.describe()}\n"
                f"The agent is a small LLM defender with no notes and no memory.\n"
                f"Predict its score.")
        try:
            raw = chat(TEACHER_MODEL,
                       PREDICT_SYS.format(floor=round(floor, 1)),
                       user, max_tokens=200, temperature=0.2,
                       tag="worldmodel:predict")
            pred = float((_json_from(raw) or {}).get("predicted_score"))
        except Exception as e:
            print(f"  {cfg.describe()}: prediction failed ({type(e).__name__})")
            continue

        scores = [run_world_episode(BlueAgent(notes="", name="probe"), cfg, s,
                                    tag="worldmodel:probe")["score"]
                  for s in (701, 702)]
        actual = st.mean(scores)
        rows.append({"world": cfg.describe(), "random_floor": round(floor, 1),
                     "predicted": pred, "actual": round(actual, 1),
                     "abs_error": round(abs(pred - actual), 1),
                     "baseline_abs_error": round(abs(floor - actual), 1)})
        print(f"  {cfg.describe()[:44]:<46} predicted {pred:8.1f}   "
              f"actual {actual:8.1f}   off by {abs(pred-actual):6.1f}")

    if not rows:
        return {"rows": [], "verdict": "no predictions produced"}

    mae = st.mean(r["abs_error"] for r in rows)
    base = st.mean(r["baseline_abs_error"] for r in rows)
    # Does it rank worlds correctly, even if magnitudes are off?
    order_ok = ([r["world"] for r in sorted(rows, key=lambda r: r["predicted"])]
                == [r["world"] for r in sorted(rows, key=lambda r: r["actual"])])
    print(f"\n  mean error            : {mae:.1f}")
    print(f"  naive baseline error  : {base:.1f}  (always guess the random floor)")
    print(f"  beats naive baseline  : {mae < base}")
    print(f"  ranks worlds correctly: {order_ok}")
    return {"rows": rows, "mae": round(mae, 1), "baseline_mae": round(base, 1),
            "beats_baseline": mae < base, "ranking_correct": order_ok}


if __name__ == "__main__":
    res = {"test1_discrimination": test_discrimination(trials=3),
           "test2_prediction": test_prediction()}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(res, f, indent=2)
    print(f"\nwritten to {OUT}")
