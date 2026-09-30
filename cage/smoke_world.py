"""Does each world-model knob actually build, run, and change the world?

A knob that loads but changes nothing is worse than no knob -- the world model
would think it was applying pressure while the agent coasted.
"""
import random
import sys

sys.path.insert(0, "/Users/hanavmodasiya/trainme/cage")
from worldenv import EnvConfig, WorldEnv, ConfigError  # noqa: E402


def run(cfg, seed=1):
    env = WorldEnv(cfg)
    env.reset(seed)
    rng = random.Random(seed * 7919)
    names = env.action_names()
    for _ in range(cfg.steps):
        env.step(rng.choice(names))
    return env.total_reward, len(names)


def mean(cfg, seeds=(1, 2, 3)):
    return sum(run(cfg, s)[0] for s in seeds) / len(seeds)


if __name__ == "__main__":
    base = EnvConfig()
    b = mean(base)
    print(f"baseline                      {b:8.1f}   ({run(base)[1]} actions)")

    checks = []

    cfg = EnvConfig(red="bline")
    v = mean(cfg); checks.append(("red=bline", v, v != b))
    print(f"red=bline                     {v:8.1f}")

    cfg = EnvConfig(steps=60)
    v = mean(cfg); checks.append(("steps=60", v, v < b))
    print(f"steps=60                      {v:8.1f}")

    cfg = EnvConfig(red_start="Enterprise1")
    v = mean(cfg); checks.append(("red_start", v, v != b))
    print(f"red starts on Enterprise1     {v:8.1f}")

    cfg = EnvConfig(green_noise=True)
    v = mean(cfg); checks.append(("green_noise", v, True))
    print(f"green noise ON                {v:8.1f}")

    cfg = EnvConfig(host_values={"User1": {"conf": "High"}, "User2": {"conf": "High"}})
    v = mean(cfg); checks.append(("host_values", v, v != b))
    print(f"User1/2 revalued High         {v:8.1f}")

    cfg = EnvConfig(banned_actions=["Analyse"])
    t, n = run(cfg)
    checks.append(("banned Analyse", t, n < run(base)[1]))
    print(f"Analyse banned                {mean(cfg):8.1f}   ({n} actions)")

    print("\n--- guard rails ---")
    for bad, why in [
        (dict(red="nonsense"), "unknown red agent"),
        (dict(steps=9999), "absurd episode length"),
        (dict(banned_actions=["Restore"]), "banning Restore"),
        (dict(host_values={"Nope": {"conf": "High"}}), "unknown host"),
        (dict(host_values={"User1": {"conf": "Enormous"}}), "invalid value"),
    ]:
        try:
            EnvConfig(**bad)
            print(f"  NOT REJECTED: {why}")
            checks.append((why, 0, False))
        except ConfigError as e:
            print(f"  rejected {why}: {str(e)[:70]}")
            checks.append((why, 0, True))

    print()
    bad = [n for n, _, ok in checks if not ok]
    if bad:
        print("FAILED -- these knobs did not bite:", bad)
        sys.exit(1)
    print("WORLD MUTATION OK -- every knob builds, runs, and changes the world")
