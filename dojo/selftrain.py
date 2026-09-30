"""Self-training: the world escalates, the agent learns from its own play.

No teacher. No advice. After each round the agent reads back its OWN game and
writes its OWN notes, using its OWN model -- nothing stronger ever tells it
anything. The notes accumulate across rounds and are the only thing carried
forward; the weights never change.

The world only ratchets up: every round's change layers onto the world so far,
and a patch that does not measurably increase difficulty is rejected.

A memoryless control plays the identical world on identical seeds every round,
so improvement can be separated from the world getting harder.
"""
import json
import os
import statistics as st
import sys
import time
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, "/Users/hanavmodasiya/trainme")
sys.path.insert(0, "/Users/hanavmodasiya/trainme/cage")

from worldenv import EnvConfig  # noqa: E402
from dojo.llm import chat, STUDENT_MODEL  # noqa: E402
from dojo.world_model import next_patch, _json_from, _action_histogram  # noqa: E402

OUT = "/Users/hanavmodasiya/trainme/results/selftrain.json"
ROUNDS = int(os.environ.get("ROUNDS", "10"))
SEEDS = [501, 502]
STEPS = int(os.environ.get("STEPS", "25"))
MAX_NOTES = 14          # soft ceiling; a rule is dropped on evidence, not for space
VAL_SEEDS = [551, 552]  # held out from training, used only to A/B note sets

# The agent talks to ITSELF here. Same model as plays the game, and it is NOT
# told the penalty table -- it has to infer what hurt from the rewards it saw.
REFLECT_SYSTEM = """You just played a round as the Blue defender and you are writing
notes to yourself before the next round, which will be harder.

You are not given the rules. Work out what cost you points from the rewards you
actually received, turn by turn.

Method -- follow it, do not skip it:
1. START from the table showing whether your actions HELD. If a host you acted on
   was compromised again a few turns later, that action did not fix it -- no
   matter how the table looked the turn after, and no matter how cheap it was.
   An action that NEVER holds is worthless: stop using it on that kind of host
   and use whichever one does hold, even if that one costs you points.
2. Beware of judging an action by the reward on the turn you used it. An action
   that costs you something now may be stopping a loss that would have repeated
   every turn for the rest of the game. Look at which hosts stayed compromised
   for many turns -- that is where your score actually went.
3. If a host stayed compromised for many turns while you kept acting on it, the
   action you were using on it does not work. Use a different one.

Then rewrite your notes: merge what you already knew with what this round taught
you and keep at most {n} rules.

Every rule must:
- be ONE short imperative sentence of the form "When X, do Y"
- be something you can check on the board at a single turn
- NAME A SPECIFIC ACTION. "Prioritise effective actions" is not a rule, it is a
  wish -- you cannot act on it. Say which action.

At least HALF your rules must tell you what TO DO, not what to avoid. A list of
only prohibitions leaves you with nothing to play. If you have ruled out every
action you have tried, your next rule must name an action you have NOT tried and
tell you to use it.

KEEPING YOUR OLD RULES:
- A rule you already had stays unless THIS round gave you evidence against it.
  Do not delete a working rule just to make room for a new one.
- Your list must not contradict itself. If a new rule says to use an action on a
  kind of host and an old rule says not to, you cannot keep both -- decide which
  one the evidence supports and drop the other. Say nothing you would not act on.
- Adding nothing is a valid answer. If this round taught you nothing new, return
  your existing rules unchanged.

Reject your own rule if it is vague ("monitor regularly", "balance your actions",
"stay updated") or if it contradicts another rule in your list. A short list of
rules you trust beats a long list you do not.

Reply as strict JSON only: {{"notes": ["...", "..."]}}"""


def _play(args):
    cfg_dict, notes, seed, role = args
    from dojo.agent import BlueAgent
    from dojo.runner import run_world_episode

    cfg = EnvConfig.from_dict(cfg_dict)
    agent = BlueAgent(notes=notes, name=role)
    r = run_world_episode(agent, cfg, seed, tag=f"selftrain:{role}")
    r["role"], r["seed"] = role, seed
    return r


def _board(obs):
    """PrettyTable text -> {host: compromised}."""
    out = {}
    for line in str(obs).splitlines():
        if not line.startswith("|"):
            continue
        c = [x.strip() for x in line.strip().strip("|").split("|")]
        if len(c) >= 5 and c[2] != "Hostname":
            out[c[2]] = c[4]
    return out


def efficacy_report(traj, lookahead=3):
    """Did the action HOLD -- or did the host come straight back?

    Do NOT measure whether the Compromised column changed: CybORG flips a host to
    'Unknown' whenever you Remove it, whether or not the attacker actually left,
    so every Remove looks like it worked. The honest signal blue can see for
    itself is persistence -- was the host compromised again a few turns later?
    Measured over real episodes: Remove on a privileged host comes back 26/26
    times; Restore on one comes back 0/7.
    """
    stats = {}
    for i, t in enumerate(traj):
        parts = str(t["action"]).split(" ", 1)
        if len(parts) != 2:
            continue
        verb, host = parts
        before = _board(t["obs"]).get(host)
        if before in (None, "No"):
            continue
        later = [_board(traj[j]["obs"]).get(host)
                 for j in range(i + 1, min(i + 1 + lookahead, len(traj)))]
        if not later:
            continue
        rec = stats.setdefault((verb, before), {"n": 0, "back": 0})
        rec["n"] += 1
        if any(x not in ("No", None) for x in later):
            rec["back"] += 1

    lines = []
    for (verb, state), rec in sorted(stats.items(), key=lambda kv: -kv[1]["n"]):
        held = rec["n"] - rec["back"]
        pct = 100 * held / rec["n"]
        verdict = ("it NEVER held" if held == 0 else
                   "it always held" if held == rec["n"] else
                   f"it held {pct:.0f}% of the time")
        lines.append(f"  {verb} on a '{state}' host: used {rec['n']}x, and the host "
                     f"was compromised again within {lookahead} turns {rec['back']}x "
                     f"-- {verdict}")
    ALL_VERBS = ["Restore", "Remove", "Analyse", "Monitor",
                 "DecoyApache", "DecoySSHD", "DecoyTomcat", "DecoyVsftpd"]
    used = {v for v, _ in stats}
    untried = [v for v in ALL_VERBS if v not in used]
    if untried:
        lines.append("")
        lines.append(f"  YOU HAVE NEVER TRIED: {', '.join(untried)}.")
        lines.append("  You have NO evidence about these -- not bad evidence, none "
                     "at all.")
        lines.append("  If everything you have tried fails to hold, the answer is "
                     "one of these.")
        lines.append("  Write a rule that makes you TRY one, or you will never "
                     "find out.")
    return "\n".join(lines) or "  (not enough data)"


def bleed_report(traj):
    """How long each host stayed compromised -- where the damage came from."""
    held = {}
    for t in traj:
        for host, state in _board(t["obs"]).items():
            if state not in ("No", "Unknown"):
                held[host] = held.get(host, 0) + 1
    if not held:
        return "  (nothing stayed compromised)"
    return "\n".join(
        f"  {h} was compromised for {n} of {len(traj)} turns"
        for h, n in sorted(held.items(), key=lambda kv: -kv[1])[:6])


def takeover(traj):
    """How bad did it end? The crown server is worth 10x any other machine."""
    if not traj:
        return {}
    b = _board(traj[-1]["obs"])
    owned = [h for h, v in b.items() if v != "No"]
    return {
        "hosts_compromised": len(owned),
        "hosts_total": len(b),
        "network_fully_taken": bool(b) and len(owned) == len(b),
        "crown_server_lost": b.get("Op_Server0", "No") != "No",
        "compromised_hosts": sorted(owned),
    }


def reflect(notes, episode, round_no):
    """The agent critiques itself. Student model only."""
    traj = episode["trajectory"]
    rows = "\n".join(
        f"  turn {t['step']:2d}: {t['action']:<24} reward {t['reward']:6.1f}"
        for t in traj)
    cur = "\n".join(f"- {x}" for x in notes) or "  (none yet)"
    user = (f"Round {round_no}. You scored {episode['score']:.1f} "
            f"(0 is perfect, more negative is worse).\n\n"
            f"Your notes going in:\n{cur}\n\n"
            f"What you did:\n{rows}\n\n"
            f"Your action mix: {_action_histogram(traj)}\n\n"
            f"DID YOUR ACTIONS HOLD? Ignore whether the table changed the turn\n"
            f"after -- it can change without the attacker leaving. What matters is\n"
            f"whether the host was compromised AGAIN a few turns later:\n"
            f"{efficacy_report(traj)}\n\n"
            f"WHERE THE DAMAGE CAME FROM:\n{bleed_report(traj)}\n\n"
            f"The network at the end:\n{episode['final_obs']}\n\n"
            f"Rewrite your notes.")
    try:
        raw = chat(STUDENT_MODEL, REFLECT_SYSTEM.format(n=MAX_NOTES), user,
                   max_tokens=800, temperature=0.4, tag="selftrain:reflect")
    except Exception:
        return notes
    got = [str(x).strip() for x in (_json_from(raw) or {}).get("notes", [])
           if str(x).strip()]
    return got[:MAX_NOTES] or notes


def validate(cfg, old_notes, new_notes):
    """A candidate rulebook has to EARN its place.

    Play the same world on held-out seeds with the incumbent notes and with the
    candidate, and keep whichever takes less damage. Without this the agent
    rewrites its rules every round with nothing pulling them toward correctness,
    which is how "use Restore" and "do not use Restore" end up in the same list.
    """
    if new_notes == old_notes:
        return old_notes, None
    old_blob = "\n".join(f"- {x}" for x in old_notes)
    new_blob = "\n".join(f"- {x}" for x in new_notes)
    jobs = ([(cfg.to_dict(), old_blob, s, "val-old") for s in VAL_SEEDS]
            + [(cfg.to_dict(), new_blob, s, "val-new") for s in VAL_SEEDS])
    with ProcessPoolExecutor(max_workers=len(jobs)) as pool:
        out = list(pool.map(_play, jobs))
    old_s = st.mean(x["score"] for x in out if x["role"] == "val-old")
    new_s = st.mean(x["score"] for x in out if x["role"] == "val-new")
    keep_new = new_s > old_s          # less damage wins
    return (new_notes if keep_new else old_notes), {
        "old_score": round(old_s, 1), "new_score": round(new_s, 1),
        "adopted": keep_new, "seeds": VAL_SEEDS}


def main():
    t0 = time.time()
    cfg = EnvConfig(red="meander", steps=STEPS)
    notes, history, rounds = [], [], []

    for rnd in range(1, ROUNDS + 1):
        cfg = EnvConfig.from_dict({**cfg.to_dict(), "steps": STEPS})
        blob = "\n".join(f"- {x}" for x in notes)

        jobs = ([(cfg.to_dict(), blob, s, "learner") for s in SEEDS]
                + [(cfg.to_dict(), "", s, "control") for s in SEEDS])
        with ProcessPoolExecutor(max_workers=len(jobs)) as pool:
            played = list(pool.map(_play, jobs))
        L = [p for p in played if p["role"] == "learner"]
        C = [p for p in played if p["role"] == "control"]
        lm, cm = st.mean(x["score"] for x in L), st.mean(x["score"] for x in C)

        print(f"\n--- round {rnd}/{ROUNDS} ---", flush=True)
        print(f"  world  : {cfg.describe()}", flush=True)
        worst = min(L, key=lambda x: x["score"])
        tk = takeover(worst["trajectory"])
        flag = ("  NETWORK FULLY TAKEN" if tk.get("network_fully_taken")
                else "  CROWN SERVER LOST" if tk.get("crown_server_lost") else "")
        print(f"  agent {lm:8.1f}   no-notes control {cm:8.1f}   "
              f"gap {lm-cm:+.1f}   ({len(notes)} notes)   "
              f"[{tk.get('hosts_compromised','?')}/{tk.get('hosts_total','?')} "
              f"hosts compromised]{flag}", flush=True)

        notes_before = list(notes)
        candidate = reflect(notes, worst, rnd)
        notes, vres = validate(cfg, notes_before, candidate)
        if vres:
            print(f"     note check: incumbent {vres['old_score']} vs "
                  f"candidate {vres['new_score']} -> "
                  f"{'ADOPTED' if vres['adopted'] else 'REJECTED, kept old notes'}",
                  flush=True)
        new = [n for n in notes if n not in notes_before]
        for n in new[:2]:
            print(f"     wrote: {n}", flush=True)

        rounds.append({
            "iteration": rnd, "config": cfg.to_dict(),
            "config_desc": cfg.describe(),
            "learner_scores": [x["score"] for x in L],
            "control_scores": [x["score"] for x in C],
            "learner_mean": lm, "control_mean": cm, "gap": lm - cm,
            "seeds": SEEDS, "notes_count": len(notes),
            "round_lessons": new,
            "notes_after": list(notes),
            "is_noise_calibration": rnd == 1,
            "learner_trajectory": worst["trajectory"],
            "learner_takeover": takeover(worst["trajectory"]),
            "note_validation": vres,
            "candidate_notes": candidate,
            "control_takeover": takeover(
                min(C, key=lambda x: x["score"])["trajectory"]),
        })
        history.append({"iteration": rnd, "learner_score": lm,
                        "control_score": cm, "config_desc": cfg.describe(),
                        "gap": lm - cm})

        if rnd == ROUNDS:
            break
        cfg, world = next_patch(cfg, history,
                                {"score": worst["score"],
                                 "final_obs": worst["final_obs"],
                                 "trajectory": worst["trajectory"]},
                                {"score": min(x["score"] for x in C),
                                 "final_obs": C[0]["final_obs"],
                                 "trajectory": C[0]["trajectory"]})
        rounds[-1]["next_patch"] = world.get("patch")
        rounds[-1]["diagnosis"] = world.get("diagnosis", "")
        rounds[-1]["targeting"] = world.get("targeting", "")
        rounds[-1]["next_floor"] = world.get("random_floor")
        if world.get("difficulty_capped"):
            print("  curriculum stops: every dial is maxed and the control has "
                  "saturated -- further rounds would train on noise", flush=True)
            break
        print(f"  world hardens: {world.get('patch')}   "
              f"floor {world.get('prev_floor')} -> {world.get('random_floor')}",
              flush=True)

    out = {"mode": "self-training, no teacher advice",
           "rounds": rounds, "notes": notes, "n_rounds": ROUNDS,
           "steps_per_episode": STEPS, "seeds": SEEDS,
           "gap_curve": [r["gap"] for r in rounds],
           "elapsed_s": round(time.time() - t0, 1)}
    with open(OUT, "w") as f:
        json.dump(out, f, indent=2)

    print("\n=== curriculum ===")
    for r in rounds:
        print(f"  r{r['iteration']:<2} floor->{str(r.get('next_floor','')):<9} "
              f"agent {r['learner_mean']:8.1f}  control {r['control_mean']:8.1f}  "
              f"gap {r['gap']:+7.1f}   {r['config_desc'][:52]}")
    print(f"\nfinal notes ({len(notes)}):")
    for i, n in enumerate(notes, 1):
        print(f"  {i}. {n}")
    print(f"\n{OUT}   ({out['elapsed_s']}s)")


if __name__ == "__main__":
    main()
