"""Ablation: a world mutator that never looks at the agent.

This is how we test whether the LLM is genuinely modelling the agent, rather
than just emitting plausible-sounding difficulty. It draws from the SAME knob
space under the SAME validation, but picks blindly -- no diagnosis, no
trajectory, no notes.

If the LLM world model is doing real work, the notes earned against it should
beat the notes earned against this on the final exam. If the two tie, the
"diagnosis" was narration and any ramp would have done.
"""
import random
import sys

sys.path.insert(0, "/Users/hanavmodasiya/trainme")
sys.path.insert(0, "/Users/hanavmodasiya/trainme/cage")

from worldenv import EnvConfig, HOSTS  # noqa: E402
from dojo.world_model import world_headroom, next_world  # noqa: E402

VALUE_LADDER = ["Low", "Medium", "High"]


def _propose(rng):
    cfg = {"red": rng.choice(["meander", "bline"]),
           "steps": 30,
           "green_noise": rng.random() < 0.5,
           "host_values": {}}
    if rng.random() < 0.5:
        host = rng.choice(HOSTS)
        cfg["host_values"] = {host: {"conf": rng.choice(VALUE_LADDER)}}
    return cfg


def next_world_random(history, learner_notes, last_learner=None,
                      last_control=None, tries=8, prev_signature=None,
                      prev_floor=None, seed=None):
    """Same signature as next_world_validated, so it is a drop-in swap."""
    rng = random.Random(seed if seed is not None else len(history) * 991 + 7)

    # Fair ablation: lessons are generated EXACTLY as in the real arm -- same
    # model, same critique prompt, same trajectory. Only the world it hands back
    # is discarded and replaced with a blind draw. So the one thing under test is
    # whether choosing the world with knowledge of the agent matters.
    try:
        _, taught = next_world(history, learner_notes, last_learner, last_control)
        lessons = taught.get("lessons", [])
        diagnosis = taught.get("diagnosis", "")
    except Exception:
        lessons, diagnosis = [], ""

    rejected = []
    for _ in range(tries):
        cfg = EnvConfig.from_dict({**_propose(rng), "note": "random mutator"})
        if prev_signature is not None and cfg.signature() == prev_signature:
            continue
        floor, ok, reason = world_headroom(cfg)
        if ok and prev_floor is not None and abs(floor - prev_floor) < 3.0:
            ok, reason = False, 'no-op world: difficulty unchanged'
        if ok:
            return cfg, {
                "diagnosis": diagnosis,
                "targeting": "ABLATION: world drawn blindly, ignoring the diagnosis",
                "lessons": lessons,
                "config": cfg.to_dict(), "config_desc": cfg.describe(),
                "random_floor": round(floor, 2), "validated": True,
                "rejected_worlds": rejected}
        rejected.append({"config_desc": cfg.describe(),
                         "floor": round(floor, 2), "reason": reason})

    cfg = EnvConfig(red="bline", note="random mutator fallback")
    floor, _, _ = world_headroom(cfg)
    return cfg, {"diagnosis": diagnosis, "targeting": "ABLATION fallback",
                 "lessons": lessons, "config": cfg.to_dict(),
                 "config_desc": cfg.describe(), "random_floor": round(floor, 2),
                 "validated": False, "rejected_worlds": rejected}
