"""run_episode: one CAGE2 episode driven by an agent, with optional teacher hints."""
import sys

sys.path.insert(0, "/Users/hanavmodasiya/trainme")
sys.path.insert(0, "/Users/hanavmodasiya/trainme/cage")

from env import DojoEnv, EVAL_SEEDS, PRACTICE_SEEDS  # noqa: E402


def run_episode(agent, seed, hint_fn=None, max_steps=30, red="meander",
                allow_eval_seed=False, tag="ep"):
    """Play one episode. Returns {'score', 'trajectory', 'seed', ...}.

    hint_fn(step, obs_text, history, env) -> str | None lets the teacher inject
    guidance before each action. That is the whole scaffolding mechanism.
    """
    if not allow_eval_seed and seed in EVAL_SEEDS:
        raise ValueError(
            f"seed {seed} is a held-out eval seed; practice may not touch it"
        )

    env = DojoEnv(red=red, max_steps=max_steps)
    obs = env.reset(seed)
    trajectory = []

    for step in range(max_steps):
        hint = hint_fn(step, obs, trajectory, env) if hint_fn else None
        action, why = agent.act(env, obs, trajectory, step, hint=hint,
                                tag=f"{tag}:s{seed}")
        obs_before = obs
        obs, reward, done, info = env.step(action)
        trajectory.append({
            "step": step + 1,
            "obs": obs_before,
            "action": action,
            "reason": why,
            "hint": hint,
            "reward": reward,
            "cumulative": env.total_reward,
        })
        if done:
            break

    return {
        "seed": seed,
        "red": red,
        "steps": len(trajectory),
        "score": env.total_reward,
        "invalid_picks": getattr(agent, "invalid_picks", 0),
        "trajectory": trajectory,
    }


def compact_trajectory(traj, keep_obs_every=0):
    """Small form for sending to the teacher: drops the big obs tables."""
    out = []
    for t in traj:
        row = {
            "step": t["step"],
            "action": t["action"],
            "reason": t["reason"],
            "reward": round(t["reward"], 2),
        }
        if keep_obs_every and t["step"] % keep_obs_every == 1:
            row["obs"] = t["obs"]
        out.append(row)
    return out


def final_state_summary(traj):
    """Last observed table -- the teacher wants to see how it ended."""
    return traj[-1]["obs"] if traj else ""


def run_world_episode(agent, cfg, seed, max_steps=None, tag="world"):
    """One episode in a world-model-generated world (WorldEnv, not DojoEnv)."""
    from worldenv import WorldEnv

    env = WorldEnv(cfg)
    obs = env.reset(seed)
    steps = max_steps or cfg.steps
    trajectory = []
    for step in range(steps):
        action, why = agent.act(env, obs, trajectory, step, hint=None,
                               tag=f"{tag}:s{seed}")
        obs_before = obs
        obs, reward, done, info = env.step(action)
        trajectory.append({
            "step": step + 1, "obs": obs_before, "action": action,
            "reason": why, "hint": None, "reward": reward,
            "cumulative": env.total_reward,
        })
        if done:
            break
    return {
        "seed": seed, "steps": len(trajectory), "score": env.total_reward,
        "invalid_picks": getattr(agent, "invalid_picks", 0),
        "final_obs": trajectory[-1]["obs"] if trajectory else "",
        "trajectory": trajectory,
    }


def random_floor(cfg, seeds=(11, 12)):
    """Cheap sanity check: is this world winnable at all, or just noise?"""
    import random as _r
    from worldenv import WorldEnv

    totals = []
    for s in seeds:
        env = WorldEnv(cfg)
        env.reset(s)
        rng = _r.Random(s * 7919)
        names = env.action_names()
        for _ in range(cfg.steps):
            env.step(rng.choice(names))
        totals.append(env.total_reward)
    return sum(totals) / len(totals)
