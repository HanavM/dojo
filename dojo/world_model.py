"""The adversarial world model.

It reads how THIS agent failed and rewrites the environment to attack that
specific weakness. It emits an EnvConfig -- data, not code -- so the world it
invents is constrained to knobs the benchmark actually exposes and validates.
"""
import json
import sys

sys.path.insert(0, "/Users/hanavmodasiya/trainme")
sys.path.insert(0, "/Users/hanavmodasiya/trainme/cage")

from worldenv import (EnvConfig, ConfigError, HOSTS, VERBS,  # noqa: E402
                      PROTECTED_VERBS, STOCK_VALUES)
from dojo.llm import chat, TEACHER_MODEL  # noqa: E402

# Measured with a random agent, 30 steps, seeds 1-3 (cage/smoke_world.py).
# The world model gets these so it does not flatten the agent on iteration one.
KNOB_GUIDE = """THE KNOBS YOU CAN TURN, and how hard each one bites.
Measured against a baseline of -30.9 (random agent, meander, 30 steps):

  red = "bline"            -> -204.7   SLEDGEHAMMER. An attacker that knows the
                                       network map and drives straight at the
                                       crown jewels. Use when the agent is too
                                       slow to react, not as a general ramp.
  host_values              -> -311.4   SLEDGEHAMMER. Raising two User hosts to
                                       "High" made the world 10x harsher. Raise
                                       ONE host one level at a time.
  green_noise = true       -> -34.3    NUDGE. Benign employee traffic that looks
                                       like reconnaissance on the status board.
                                       Punishes an agent that treats every blip
                                       as hostile.
  host_values, one host    -> ramp     Your MAIN dial. Raise ONE machine one
                                       level (None->Low->Medium->High) to make
                                       the agent's blind spot expensive. If it
                                       ignores the Operational subnet, make
                                       Op_Host hosts cost real points.
  steps                    -> avoid changing. A longer episode scores worse purely
                                       because damage accumulates; it is not a
                                       harder world, just a longer one.

Turn ONE sledgehammer OR one-to-two nudges per iteration. Never two sledgehammers.

You may NOT take tools away from the agent. banned_actions is disabled. At test
time the agent will have every tool, so training it without one prepares it for a
world that does not exist. Make the WORLD harder; never make the AGENT weaker.

Do NOT set red_start. It is locked to User0: moving Red's foothold does not
relocate the attacker, it disables it, and the world becomes trivial.

Every world you build must DIFFER from the previous one. Re-sending the same
config wastes the agent's paid iteration. If your diagnosis has not changed,
attack the same weakness from a different angle.

A world only counts if a RANDOM agent visibly suffers in it. If you are told a
proposal was rejected as trivial, you removed the threat instead of sharpening
it -- put the pressure somewhere else."""

SYSTEM = """You are an adversarial world model. A defending agent is training against
you. Your job is NOT to be maximally cruel -- it is to find the ONE thing this
specific agent is bad at and build a world that forces it to fix that.

The environment is CAGE Challenge 2 network defence. Red attacks a 13-host network;
the agent plays Blue. Score is summed negative penalties, 0 is perfect.

Ground truth about the game:
  - Restore is the ONLY action that clears privileged (root) access. It costs -1.0.
  - Remove kills user-level shells only; on a privileged host it is a wasted turn.
  - Analyse and Monitor are free but fix nothing -- they are where weak agents hide.
  - Penalties per step: Enterprise root -1.0 each, Op_Server0 root -1.0,
    User root -0.1, an Impact on Op_Server0 -10.0.

""" + KNOB_GUIDE + """

WHAT EACH MACHINE IS CURRENTLY WORTH (raising a host to the value it ALREADY has
does nothing and wastes the agent's paid iteration):
""" + "\n".join(
    f"  {h:<12} conf={v['conf']:<7} avail={v['avail']}"
    for h, v in STOCK_VALUES.items()) + """

Note most Op_Host and User machines are worth NOTHING today -- raising one of
those is the change with the most room to move. The Enterprise hosts and
Op_Server0 are already Medium.

HOSTS: """ + ", ".join(HOSTS) + """
BANNABLE VERBS: """ + ", ".join(v for v in VERBS if v not in PROTECTED_VERBS) + """
(Monitor, Sleep and Restore can never be banned.)

You are shown the LEARNER (an agent carrying notes from past rounds) and the
CONTROL (the same model with no notes and no memory) playing the SAME world. The
gap between them is what learning is worth. If the gap is not growing, your last
world did not teach anything -- change WHICH weakness you attack, not just how hard.

Reply as strict JSON only:
{
  "diagnosis": "one sentence naming this agent's single biggest weakness, citing what it actually did",
  "targeting": "one sentence on which knob attacks that weakness and why",
  "config": {"red": "meander|bline", "steps": 30, "green_noise": false,
             "host_values": {"<host>": {"conf": "Low|Medium|High"}}},
  "lessons": ["2-4 one-sentence rules the learner should write down"],
  "predicted_learner_score": <number: what you expect the learner to actually
      score in the world you just built. Negative. This is checked against the
      real result afterwards, so guess honestly rather than optimistically.>
}"""


def _json_from(raw):
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.lstrip().lower().startswith("json"):
            raw = raw.lstrip()[4:]
    a, b = raw.find("{"), raw.rfind("}")
    if a >= 0 and b > a:
        try:
            return json.loads(raw[a:b + 1])
        except json.JSONDecodeError:
            return None
    return None


def _action_histogram(traj):
    counts = {}
    for t in traj:
        verb = str(t.get("action", "")).split(" ")[0]
        counts[verb] = counts.get(verb, 0) + 1
    return ", ".join(f"{v}x{n}" for v, n in
                     sorted(counts.items(), key=lambda kv: -kv[1]))


def _round_summary(label, result):
    if not result:
        return f"{label}: (not played)"
    traj = result.get("trajectory", [])
    return (f"{label}: score {result.get('score', 0):.1f}\n"
            f"  action mix: {_action_histogram(traj)}\n"
            f"  final board:\n{_indent(result.get('final_obs', ''))}")


def _indent(s, pad="    "):
    return "\n".join(pad + l for l in str(s).splitlines()[:20])


def next_world(history, learner_notes, last_learner=None, last_control=None):
    """Diagnose the agent and emit the next world.

    history: [{iteration, config, learner_score, control_score, gap}]
    Returns (EnvConfig, payload_dict).
    """
    if history:
        hist = "\n".join(
            f"  iter {h['iteration']}: gap {h['gap']:+.1f} "
            f"(learner {h['learner_score']:.1f} vs control {h['control_score']:.1f}) "
            f"-- world was: {h['config_desc']}"
            for h in history)
    else:
        hist = "  (none yet -- this is the first world)"

    notes = "\n".join(f"- {l}" for l in (learner_notes or [])) or "  (empty)"

    user = f"""Rounds so far (gap = how much the notes were worth; bigger is better):
{hist}

The learner's current notes:
{notes}

Last round, both agents played the same world:
{_round_summary("LEARNER (has notes)", last_learner)}

{_round_summary("CONTROL (no notes, no memory)", last_control)}

Diagnose the learner's single biggest remaining weakness and build the next world
to attack it."""

    raw = chat(TEACHER_MODEL, SYSTEM, user, max_tokens=900, temperature=0.4,
               tag="world_model:next")
    data = _json_from(raw) or {}

    cfg_dict = data.get("config") or {}
    cfg_dict["note"] = data.get("targeting", "")
    try:
        cfg = EnvConfig.from_dict(cfg_dict)
    except (ConfigError, TypeError) as e:
        # The world model proposed something the benchmark refuses to build.
        # Fall back to a nudge rather than failing the paid iteration.
        cfg = EnvConfig(green_noise=True,
                        note=f"fallback after invalid config: {str(e)[:120]}")
        data["config_error"] = str(e)[:200]

    pred = data.get("predicted_learner_score")
    try:
        pred = float(pred)
    except (TypeError, ValueError):
        pred = None

    payload = {
        "predicted_learner_score": pred,
        "diagnosis": str(data.get("diagnosis", "")).strip(),
        "targeting": str(data.get("targeting", "")).strip(),
        "lessons": [str(x).strip() for x in data.get("lessons", []) if str(x).strip()][:4],
        "config": cfg.to_dict(),
        "config_desc": cfg.describe(),
    }
    if "config_error" in data:
        payload["config_error"] = data["config_error"]
    return cfg, payload


# -- headroom guard --------------------------------------------------------
# A world is only a test if an incompetent agent visibly suffers in it. Measured
# reference points (random agent, 3 seeds): stock meander -30.9, bline -210,
# a world with the attacker disabled -5.7.
MIN_DAMAGE = 15.0     # random must lose at least this much, or there is nothing to defend


def world_headroom(cfg):
    """Run a random agent. Returns (floor, ok, reason)."""
    from dojo.runner import random_floor
    floor = random_floor(cfg, seeds=(11, 12, 13))
    if floor > -MIN_DAMAGE:
        return floor, False, (
            f"trivial world: a random agent only loses {floor:.1f}, so there is "
            f"nothing to defend and skill cannot show. Need worse than "
            f"-{MIN_DAMAGE:.0f}.")
    return floor, True, ""


def next_world_validated(history, learner_notes, last_learner=None,
                         last_control=None, tries=3, prev_signature=None,
                         prev_floor=None):
    """Propose a world, then PROVE it is a test before handing it over.

    The retry costs LLM calls but not another paid iteration -- the agent paid
    for a usable world, not for a proposal.
    """
    rejected = []
    for attempt in range(tries):
        cfg, payload = next_world(history, learner_notes, last_learner, last_control)
        if rejected:
            payload.setdefault("rejected_worlds", []).extend(rejected)
        if prev_signature is not None and cfg.signature() == prev_signature:
            reason = ("identical to the world just played -- the agent paid for a "
                      "new world, not a repeat. Attack the weakness differently.")
            rejected.append({"config_desc": cfg.describe(), "floor": None,
                             "reason": reason})
            history = list(history) + [{
                "iteration": "rejected", "gap": 0.0, "learner_score": 0.0,
                "control_score": 0.0,
                "config_desc": f"REJECTED {cfg.describe()} -- {reason}"}]
            continue

        floor, ok, reason = world_headroom(cfg)
        payload["random_floor"] = round(floor, 2)
        # A config that differs on paper but leaves difficulty untouched is a
        # no-op dressed as a change.
        if ok and prev_floor is not None and abs(floor - prev_floor) < 3.0:
            ok, reason = False, (
                f"no-op world: difficulty is unchanged (random floor {floor:.1f} "
                f"vs {prev_floor:.1f} last round). The config differs on paper but "
                f"builds the same world. Change something that actually bites.")
            payload["validated"] = False
        if ok:
            payload["validated"] = True
            return cfg, payload
        rejected.append({"config_desc": cfg.describe(), "floor": round(floor, 2),
                         "reason": reason})
        # Tell the model why, so the next proposal is not the same mistake.
        learner_notes = list(learner_notes or [])
        history = list(history) + [{
            "iteration": "rejected", "gap": 0.0,
            "learner_score": 0.0, "control_score": 0.0,
            "config_desc": f"REJECTED {cfg.describe()} -- {reason}",
        }]

    # Nothing validated: fall back to a measured world that is not a repeat.
    for fb in (EnvConfig(red="bline", note="fallback"),
               EnvConfig(red="bline", green_noise=True, note="fallback"),
               EnvConfig(red="meander", green_noise=True, note="fallback"),
               EnvConfig(red="bline", host_values={"Op_Host0": {"conf": "Medium"}},
                         note="fallback")):
        if prev_signature is None or fb.signature() != prev_signature:
            cfg = fb
            break
    floor, _, _ = world_headroom(cfg)
    return cfg, {"diagnosis": payload.get("diagnosis", ""),
                 "targeting": "fallback to a known-hard world",
                 "lessons": payload.get("lessons", []),
                 "config": cfg.to_dict(), "config_desc": cfg.describe(),
                 "random_floor": round(floor, 2), "validated": False,
                 "rejected_worlds": rejected}


# =====================================================================
# ADVICE OFF. The world model shapes the environment and says nothing to
# the agent. The agent learns from its own play or not at all.
# =====================================================================
from dojo.teacher import MECHANICS  # noqa: E402

PATCH_SYSTEM = """You are an adversarial curriculum designer. A defending agent is
training. Your only job is to make the next world HARDER in the place this agent
is weakest. You do NOT talk to the agent and you do NOT give it advice -- it
learns from its own play. You only turn dials on the world.

The environment is CAGE Challenge 2 network defence. Score is summed negative
penalties; 0 is perfect.

""" + MECHANICS + """

""" + KNOB_GUIDE + """

IMPORTANT: you emit a PATCH, not a whole world. Your change is LAYERED on top of
the world so far, which already contains every earlier round's change. Difficulty
only ratchets up. Send just the one or two dials you want to move this round.

Reply as strict JSON only:
{
  "diagnosis": "one sentence on this agent's weakest point, citing what it did",
  "targeting": "one sentence on why this patch attacks that",
  "patch": {"red": "bline"  (only to escalate),
            "green_noise": true,
            "host_values": {"<host>": {"conf": "Low|Medium|High"}}}
}
Include ONLY the keys you are changing. An empty patch is not allowed."""


def next_patch(current, history, last_learner=None, last_control=None, tries=3):
    """Pick the next escalation. Returns (new_cfg, payload). No lessons, ever."""
    from dojo.runner import random_floor

    hist = "\n".join(
        f"  round {h['iteration']}: agent scored {h['learner_score']:.1f} "
        f"(no-notes control {h['control_score']:.1f}) in: {h['config_desc']}"
        for h in history) or "  (none yet)"

    base_floor = random_floor(current, seeds=(11, 12, 13))
    user = (f"The world so far (your patch layers onto this):\n  {current.describe()}\n"
            f"  a random agent loses {base_floor:.1f} in it\n\n"
            f"Rounds so far:\n{hist}\n\n"
            f"{_round_summary('THE AGENT last round', last_learner)}\n\n"
            f"{_round_summary('A NO-NOTES CONTROL, same world', last_control)}\n\n"
            f"Emit the patch that makes this world hardest for THIS agent.")

    rejected = []
    for _ in range(tries):
        raw = chat(TEACHER_MODEL, PATCH_SYSTEM, user, max_tokens=600,
                   temperature=0.5, tag="curriculum:patch")
        data = _json_from(raw) or {}
        patch = data.get("patch") or {}
        try:
            cand = current.stack(patch)
        except (ConfigError, TypeError) as e:
            rejected.append({"patch": patch, "reason": str(e)[:140]})
            continue

        if cand.signature() == current.signature():
            rejected.append({"patch": patch,
                             "reason": "patch changed nothing after ratcheting"})
            continue

        floor = random_floor(cand, seeds=(11, 12, 13))
        if floor > base_floor - 2.0:       # must actually bite
            rejected.append({"patch": patch, "floor": round(floor, 1),
                             "reason": f"world got no harder ({floor:.1f} vs "
                                       f"{base_floor:.1f})"})
            continue
        # Pace it. One round must not make the world unrecognisably harder --
        # otherwise the biggest dial gets spent at round 2 and, because the
        # ratchet cannot reverse, the rest of the curriculum has nothing left.
        if floor < base_floor * 3 - 20:
            rejected.append({"patch": patch, "floor": round(floor, 1),
                             "reason": f"too big a jump in one round "
                                       f"({base_floor:.1f} -> {floor:.1f}); "
                                       f"escalate gradually"})
            continue

        return cand, {
            "diagnosis": str(data.get("diagnosis", "")).strip(),
            "targeting": str(data.get("targeting", "")).strip(),
            "patch": patch,
            "config": cand.to_dict(), "config_desc": cand.describe(),
            "random_floor": round(floor, 2), "prev_floor": round(base_floor, 2),
            "validated": True, "rejected_patches": rejected, "lessons": [],
        }

    # Nothing the model proposed bit. Walk a known ladder -- but hold it to the
    # SAME bar: a fallback that makes the world easier is not an escalation.
    best = None
    for fb in ({"red": "bline"},
               {"host_values": {"Op_Host0": {"conf": "Medium"}}},
               {"host_values": {"Op_Host1": {"conf": "High"}}},
               {"host_values": {"Op_Host2": {"conf": "High"}}},
               {"host_values": {"User1": {"conf": "Medium"}}},
               {"host_values": {"User2": {"conf": "High"}}},
               {"host_values": {"User3": {"conf": "High"}}},
               {"host_values": {"User4": {"conf": "High"}}},
               {"host_values": {"Defender": {"conf": "High"}}},
               {"green_noise": True}):
        cand = current.stack(fb)
        if cand.signature() == current.signature():
            continue
        floor = random_floor(cand, seeds=(11, 12, 13))
        if floor <= base_floor - 2.0 and floor >= base_floor * 3 - 20:
            return cand, {"diagnosis": str(data.get("diagnosis", "")).strip(),
                          "targeting": "fallback escalation", "patch": fb,
                          "config": cand.to_dict(), "config_desc": cand.describe(),
                          "random_floor": round(floor, 2),
                          "prev_floor": round(base_floor, 2),
                          "validated": False, "rejected_patches": rejected,
                          "lessons": []}
        rejected.append({"patch": fb, "floor": round(floor, 1),
                         "reason": "fallback made the world no harder"})
        if best is None or floor < best[1]:
            best = (cand, floor, fb)

    # Everything failed to harden. Take the least-bad and say so honestly.
    if best is not None:
        cand, floor, fb = best
        return cand, {"diagnosis": str(data.get("diagnosis", "")).strip(),
                      "targeting": "NO DIAL HARDENED THIS WORLD -- difficulty is capped",
                      "patch": fb, "config": cand.to_dict(),
                      "config_desc": cand.describe(),
                      "random_floor": round(floor, 2),
                      "prev_floor": round(base_floor, 2),
                      "validated": False, "difficulty_capped": True,
                      "rejected_patches": rejected, "lessons": []}
    return current, {"diagnosis": "", "targeting": "exhausted every dial",
                     "patch": {}, "config": current.to_dict(),
                     "config_desc": current.describe(),
                     "random_floor": round(base_floor, 2),
                     "prev_floor": round(base_floor, 2),
                     "validated": False, "rejected_patches": rejected,
                     "lessons": []}
