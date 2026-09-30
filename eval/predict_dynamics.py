"""The real world-model test: can it predict how the environment RESPONDS?

A world model is a model of dynamics: given the current state and the action
taken, say what happens next. Not "how will this end" -- "what happens on the
very next step".

We quiz it on real transitions pulled from real episodes:
    show   : the board at step t, and the action the agent took
    ask    : the damage that turn, and which machines change hands
    check  : against what actually happened at step t+1

The whole difficulty is that MOST STEPS CHANGE NOTHING. "Predict no change"
scores well on raw accuracy while knowing nothing. So everything here is scored
against trivial baselines, and separately on the steps where the world actually
moved -- which is the only place a model can show itself.
"""
import glob
import json
import os
import random
import re
import statistics as st
import sys

sys.path.insert(0, "/Users/hanavmodasiya/trainme")
sys.path.insert(0, "/Users/hanavmodasiya/trainme/cage")

from dojo.llm import chat, TEACHER_MODEL  # noqa: E402
from dojo.world_model import _json_from  # noqa: E402
from dojo.teacher import MECHANICS  # noqa: E402

OUT = "/Users/hanavmodasiya/trainme/results/dynamics_proof.json"
N_TRANSITIONS = 40

SYSTEM = """You are the simulator for CAGE Challenge 2 network defence. You are given
the current state of the network and the single action Blue is about to take. Your
job is to say what the environment does in response.

""" + MECHANICS + """

Also: Red acts every turn too, so the board can change for reasons that have
nothing to do with Blue's action. Red starts on User0 and spreads toward
Op_Server0 via the Enterprise subnet.

Reply as strict JSON only:
{
  "damage_this_turn": <number, 0 or negative -- the reward Blue receives this step>,
  "hosts_changing": [<hostnames whose Compromised column will be DIFFERENT next step>],
  "reasoning": "one short line"
}"""


# ---------------------------------------------------------------- parsing
def parse_board(obs):
    """PrettyTable text -> {host: (activity, compromised)}."""
    out = {}
    for line in str(obs).splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 5 or cells[2] == "Hostname":
            continue
        out[cells[2]] = (cells[3], cells[4])
    return out


def compromised_map(board):
    return {h: v[1] for h, v in board.items()}


def board_text(board):
    return "\n".join(f"  {h:<12} activity={a:<8} compromised={c}"
                     for h, (a, c) in board.items())


# ---------------------------------------------------------------- sampling
def load_transitions():
    """(board_t, action, reward_t, changed_hosts) from every episode we have."""
    trans = []
    for path in glob.glob("/Users/hanavmodasiya/trainme/results/gauntlet*.json"):
        try:
            data = json.load(open(path))
        except (json.JSONDecodeError, OSError):
            continue
        for rnd in data.get("rounds", []):
            trajs = list(rnd.get("all_learner_trajectories", {}).values()) \
                    or [rnd.get("learner_trajectory", [])]
            for traj in trajs:
                for i in range(len(traj) - 1):
                    a, b = traj[i], traj[i + 1]
                    if "obs" not in a or "obs" not in b:
                        continue
                    ba, bb = parse_board(a["obs"]), parse_board(b["obs"])
                    if not ba or not bb:
                        continue
                    ca, cb = compromised_map(ba), compromised_map(bb)
                    changed = sorted(h for h in ca if ca.get(h) != cb.get(h))
                    trans.append({
                        "board": ba, "action": a["action"],
                        "reward": a["reward"],
                        "prev_reward": traj[i - 1]["reward"] if i else 0.0,
                        "changed": changed,
                    })
    return trans


def sample(trans, n, rng):
    """Half the sample from steps where the world MOVED -- otherwise the test is
    dominated by quiet steps where 'nothing happens' is free."""
    moved = [t for t in trans if t["changed"]]
    still = [t for t in trans if not t["changed"]]
    rng.shuffle(moved); rng.shuffle(still)
    half = n // 2
    return moved[:half] + still[:n - half]


# ---------------------------------------------------------------- the test
def ask(t):
    user = (f"Current board:\n{board_text(t['board'])}\n\n"
            f"Blue's action this turn: {t['action']}\n\n"
            f"What does the environment do in response?")
    raw = chat(TEACHER_MODEL, SYSTEM, user, max_tokens=300, temperature=0.0,
               tag="dynamics:predict")
    d = _json_from(raw) or {}
    try:
        dmg = float(d.get("damage_this_turn"))
    except (TypeError, ValueError):
        dmg = None
    hosts = [str(h).strip() for h in (d.get("hosts_changing") or [])]
    return dmg, hosts, str(d.get("reasoning", ""))[:120]


def main():
    rng = random.Random(7)
    trans = load_transitions()
    if not trans:
        print("no transitions with board state found -- run a gauntlet first")
        return
    moved = sum(1 for t in trans if t["changed"])
    print(f"{len(trans)} transitions available "
          f"({moved} where the board changed, {len(trans)-moved} where it did not)")
    batch = sample(trans, N_TRANSITIONS, rng)
    print(f"testing on {len(batch)} of them (half from each)\n")

    rows = []
    for i, t in enumerate(batch, 1):
        try:
            dmg, hosts, why = ask(t)
        except Exception as e:
            print(f"  {i:2d}. ERROR {type(e).__name__}")
            continue
        truth = set(t["changed"])
        pred = set(hosts)
        rows.append({
            "action": t["action"], "true_reward": t["reward"],
            "pred_reward": dmg,
            "true_changed": sorted(truth), "pred_changed": sorted(pred),
            "tp": len(truth & pred), "fp": len(pred - truth), "fn": len(truth - pred),
            "prev_reward": t["prev_reward"], "reasoning": why,
        })
        mark = "moved" if truth else "still"
        print(f"  {i:2d}. [{mark}] {t['action']:<22} "
              f"dmg true {t['reward']:6.1f} pred {str(dmg):>7}   "
              f"changed true {sorted(truth) or '-'} pred {sorted(pred) or '-'}")

    # ---- damage prediction, vs a persistence baseline -------------------
    ok = [r for r in rows if r["pred_reward"] is not None]
    mae = st.mean(abs(r["pred_reward"] - r["true_reward"]) for r in ok) if ok else None
    base_mae = st.mean(abs(r["prev_reward"] - r["true_reward"]) for r in ok) if ok else None
    zero_mae = st.mean(abs(r["true_reward"]) for r in ok) if ok else None

    # ---- state-change prediction, vs "predict nothing changes" ----------
    TP = sum(r["tp"] for r in rows); FP = sum(r["fp"] for r in rows)
    FN = sum(r["fn"] for r in rows)
    prec = TP / (TP + FP) if TP + FP else 0.0
    rec = TP / (TP + FN) if TP + FN else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0

    moved_rows = [r for r in rows if r["true_changed"]]
    still_rows = [r for r in rows if not r["true_changed"]]
    caught = sum(1 for r in moved_rows if r["pred_changed"])
    quiet_ok = sum(1 for r in still_rows if not r["pred_changed"])

    print("\n" + "=" * 70)
    print("DAMAGE PREDICTION (the reward the agent receives this turn)")
    print("=" * 70)
    if ok:
        print(f"  world model mean error   : {mae:6.2f}")
        print(f"  baseline: repeat last turn: {base_mae:6.2f}")
        print(f"  baseline: always guess 0  : {zero_mae:6.2f}")
        print(f"  beats persistence baseline: {mae < base_mae}")
        print(f"  beats always-zero baseline: {mae < zero_mae}")

    print("\n" + "=" * 70)
    print("STATE-CHANGE PREDICTION (which machines change hands next step)")
    print("=" * 70)
    print(f"  precision {prec:.2f}   recall {rec:.2f}   F1 {f1:.2f}")
    print(f"  on steps where the board MOVED : predicted a change in "
          f"{caught}/{len(moved_rows)}")
    print(f"  on steps where it stayed STILL : correctly said nothing in "
          f"{quiet_ok}/{len(still_rows)}")
    print("\n  'predict nothing ever changes' baseline would score:")
    print(f"     precision 0.00  recall 0.00  F1 0.00")
    print(f"     moved {0}/{len(moved_rows)}   still {len(still_rows)}/{len(still_rows)}")

    res = {"n_tested": len(rows),
           "damage": {"mae": round(mae, 3) if ok else None,
                      "baseline_persistence_mae": round(base_mae, 3) if ok else None,
                      "baseline_zero_mae": round(zero_mae, 3) if ok else None,
                      "beats_persistence": bool(ok and mae < base_mae),
                      "beats_zero": bool(ok and mae < zero_mae)},
           "state_change": {"precision": round(prec, 3), "recall": round(rec, 3),
                            "f1": round(f1, 3), "tp": TP, "fp": FP, "fn": FN,
                            "moved_detected": f"{caught}/{len(moved_rows)}",
                            "still_correct": f"{quiet_ok}/{len(still_rows)}"},
           "rows": rows}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(res, f, indent=2)
    print(f"\nwritten to {OUT}")


if __name__ == "__main__":
    main()
