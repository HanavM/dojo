"""Stage 2 check: the LLM blue agent actually plays an episode end to end."""
import sys
import time

sys.path.insert(0, "/Users/hanavmodasiya/trainme")

from dojo.agent import BlueAgent
from dojo.runner import run_episode

if __name__ == "__main__":
    t0 = time.time()
    agent = BlueAgent(notes="", name="smoke")
    ep = run_episode(agent, seed=1, max_steps=10, tag="smoke")
    for t in ep["trajectory"]:
        print(f"  {t['step']:2d}  {t['action']:<26} r={t['reward']:6.1f}  {t['reason'][:60]}")
    print(f"\nscore={ep['score']:.2f} steps={ep['steps']} "
          f"invalid_picks={ep['invalid_picks']} elapsed={time.time()-t0:.1f}s")
    assert ep["steps"] == 10, "wrong episode length"
    assert ep["invalid_picks"] <= 3, "too many invalid action picks"
    print("STAGE 2 OK")
