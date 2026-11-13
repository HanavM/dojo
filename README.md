# Dojo — an on-demand teacher that agents buy

**Won 3rd overall at Solana Foundation's Agent Hackathon. Theme: build something an agent would buy. Payments over pay.sh.**

An LLM agent meets a task it was never trained for — defending a 13-machine
network against an intruder. It pays **$0.05** to open a training session. An
adversarial *environment model* watches it play and rewrites the network to
attack whatever it is worst at, round after round. The agent keeps notes and
reads them before acting.

No fine-tuning anywhere. Same model, same weights — the only thing that changes
between rounds is the text above the observation.

## The headline result

Four fixed environments the agent never trained on, all tools available,
held-out seeds:

| environment | no learning | **with learning** |
|---|---|---|
| Fast attacker | −28.1 | **−13.9** |
| Long siege | −57.6 | **−22.9** |
| High stakes | −21.1 | **−13.8** |
| Noisy network | −77.1 | **−26.5** |
| **overall** | **−46.0** | **−19.3** |
| catastrophic episodes | 1/12 | **0/12** |

Score is accumulated damage; 0 is perfect. **2.4× less damage on environments it
never saw, and zero catastrophic failures** — with no teacher in the loop. The
agent wrote every one of those notes itself.

## The benchmark

CAGE Challenge 2 (CybORG 2.1), `Scenario2`. 13 machines in three subnets. A Red
attacker starts on `User0` and works toward `Op_Server0`. Blue gets one action
per turn from 145 options. Score is summed negative penalties.

The rules Blue is never told, and has to work out:

| | per turn |
|---|---|
| Red holds root on an Enterprise host | −1.0 each |
| Red holds root on `Op_Server0` | −1.0 |
| Red holds root on a User host | −0.1 |
| Red ran Impact on `Op_Server0` | −10.0 |
| `Restore` | −1.0 one-off |

`Restore` is the only action that clears root. `Remove` kills user-level shells
only. `Analyse` and `Monitor` are free and fix nothing — which is exactly where a
weak agent hides.

## What we learned building it

Three findings, in the order we hit them.

**1. The observation lies about which actions worked.** CybORG flips a host to
`Unknown` whenever you `Remove` it, whether or not the attacker left. So from
inside the game, `Remove` appears to work every single time. The agent taught
itself to use the one action that never helps — correctly reasoning from a
display that misleads. The honest signal is *persistence*: measured over real
episodes, `Remove` on a privileged host comes back **26/26 times**, `Restore`
comes back **0/7**. Once the agent could see that, it reversed itself.

**2. Notes adopted on faith degrade into nonsense.** Early runs let the agent
rewrite its rulebook freely each round. It ended up holding *"use Restore"* and
*"do not use Restore"* simultaneously, and scored **−238.8** on the exam — five
times worse than having no notes at all. The fix: a candidate rulebook must beat
the incumbent on held-out seeds before it is adopted. Three adopted, three
rejected — including one in round 1 that was worse than having no notes, which
the old system would have kept and compounded. Same agent, same curriculum:
**−238.8 → −19.3**.

**3. The adversarial targeting is the weakest link.** An ablation swapped the
environment model for one that picks worlds *at random* from the same knobs, with
identical note-writing. It scored the same (−21.2 vs −20.4). The environment
model diagnoses the agent accurately — 9/9 on planted weaknesses — but its choice
of *which* world to build is close to arbitrary, and nothing forces the change to
follow from the diagnosis. Documented rather than hidden; see
`results/worldmodel_proof.json`.

## Is the environment model a "world model"?

Tested directly, in `eval/`:

| claim | verdict |
|---|---|
| Reads the agent's behaviour | **Yes** — named a planted weakness 9/9, never confused over- with under-use |
| Predicts environment dynamics | **Weakly** — F1 0.47 against a 0.00 baseline; over-predicts danger |
| Ranks world difficulty | **Yes** |
| Predicts how well the agent will do | **No** — assumes random-level play |
| Turns its diagnosis into a targeted world | **Not shown** — random selection does as well |

It is an accurate diagnostician of the agent with a rough sense of difficulty.
Calling it a world model would overstate it.

## Layout

```
cage/
  env.py            DojoEnv — obs as a text table, 145 named actions
  worldenv.py       the mutable environment: the knobs a model may turn,
                    with ratcheting difficulty and guard rails
  smoke_random.py   Stage 1 check: random agent, determinism assert
  smoke_world.py    proves every knob builds, runs, and changes the world
dojo/
  llm.py            Azure AI Foundry client + JSONL logging of every call
  agent.py          the agent: reads notes + board, picks an action
  runner.py         run_episode / run_world_episode / random_floor
  selftrain.py      the main loop: play, self-reflect, validate, escalate
  world_model.py    the environment model — diagnosis + escalation patches
  random_world.py   ablation: same knobs, chosen blindly
  teacher.py        FastAPI product: /learn/*, /gauntlet/*
  payments.py       PAYMENTS=mock | paysh behind one interface
  live_demo.py      streams a real run over SSE
eval/
  final_exam.py       held-out environments, learning vs no learning
  prove_worldmodel.py discrimination + prediction tests
  predict_dynamics.py can it predict how the environment responds?
results/
  live.html         the demo — press Start, step through a real run
  selftrain.json    every round, note set, and validation decision
  final_exam.json   the held-out results
paywall.yml         the pay.sh gate spec
```

## Payments

Two backends behind one interface:

- `PAYMENTS=mock` — local ledger, used for all evaluation runs
- `PAYMENTS=paysh` — a real `pay gate` in front, settling on Solana

```sh
PAYMENTS=paysh uvicorn dojo.teacher:app --port 8001
pay --sandbox gate api paywall.yml --bind 127.0.0.1:1402

pay --sandbox curl -X POST http://127.0.0.1:1402/learn/start \
  -H 'content-type: application/json' -d '{"task_description":"..."}'
```

Unpaid → `402` with a pricing body. Paid → `200`, an on-chain receipt, a session
id. Follow-up calls are free within that session.

**Everything ran in `--sandbox` on a hosted localnet. No real funds were spent.**

## Running it

```sh
# the benchmark (its own venv; CybORG 2.1 needs numpy<2)
git clone --depth 1 https://github.com/cage-challenge/cage-challenge-2.git cage/cage-challenge-2
python3.11 -m venv cage/venv
cage/venv/bin/pip install "numpy<2" "gym==0.26.2" pyyaml prettytable paramiko \
    docutils pytest openai fastapi "uvicorn[standard]" httpx azure-identity
cage/venv/bin/pip install -e cage/cage-challenge-2/CybORG

az login   # inference runs on Azure AI Foundry; no API keys in the repo

cage/venv/bin/python cage/smoke_random.py    # benchmark works + is deterministic
cage/venv/bin/python cage/smoke_world.py     # every difficulty knob bites
ROUNDS=8 STEPS=25 cage/venv/bin/python dojo/selftrain.py
cage/venv/bin/python eval/final_exam.py
python3 results/build_live.py && open results/live.html
```

Models: `gpt-4o-mini` as the agent, `gpt-4o` as the environment model. Override
with `DOJO_STUDENT_MODEL` / `DOJO_TEACHER_MODEL`.

## Caveats worth stating

- **Small samples.** 12 episodes per arm on the exam, 2 seeds per training round.
  The exam gap is large and consistent across all four environments; individual
  training rounds are noisy.
- **CybORG uses the global RNG**, so episodes run in separate processes. Running
  them as threads silently destroys reproducibility.
- **The curriculum runs out of dials.** Once every knob is maxed and the control
  saturates, further rounds train on noise — the loop now stops there.
