"""Stage 1 check: random blue agent, 2 episodes of 30 steps vs Meander.

Also asserts the thing we most need to be true: same seed -> same episode.
"""
import random
import sys
sys.path.insert(0, '/Users/hanavmodasiya/trainme/cage')
from env import DojoEnv


def run(seed, max_steps=30, verbose=False):
    env = DojoEnv(red='meander', max_steps=max_steps)
    obs = env.reset(seed)
    if verbose:
        print(obs)
        print(env.action_menu())
    rng = random.Random(seed * 7919)   # action choice RNG, separate from env
    names = env.action_names()
    rewards = []
    while True:
        obs, r, done, info = env.step(rng.choice(names))
        rewards.append(r)
        if done:
            break
    return env.total_reward, rewards


if __name__ == '__main__':
    print('=== episode seed=1 ===')
    t1, r1 = run(1, verbose=True)
    print(f'steps={len(r1)} total_reward={t1:.2f}')
    print('=== episode seed=2 ===')
    t2, r2 = run(2)
    print(f'steps={len(r2)} total_reward={t2:.2f}')
    print('=== determinism: seed=1 again ===')
    t1b, _ = run(1)
    print(f'total_reward={t1b:.2f}  match={abs(t1 - t1b) < 1e-9}')
    assert len(r1) == 30 and len(r2) == 30, 'episode length wrong'
    assert abs(t1 - t1b) < 1e-9, 'NOT deterministic under seed'
    print('\nSTAGE 1 OK')
