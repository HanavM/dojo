"""Dojo teacher server: an on-demand teacher an agent can buy.

  POST /learn/start   $0.05  -> session_id, first practice config, scaffold 3
  POST /learn/hint    free   -> per-step guidance (scaffold levels 3 and 2)
  POST /learn/submit  free   -> critique lessons, next practice, next scaffold

Session state lives in dojo/sessions/*.json.
"""
import json
import os
import sys
import time
import uuid

sys.path.insert(0, "/Users/hanavmodasiya/trainme")
sys.path.insert(0, "/Users/hanavmodasiya/trainme/cage")

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from dojo import payments
from dojo.llm import chat, TEACHER_MODEL

SESSION_DIR = "/Users/hanavmodasiya/trainme/dojo/sessions"

MAX_PRACTICE = 6
PASS_SCORE = -15.0          # 30-step Meander: random is about -30
PRACTICE_SEEDS = list(range(1, 21))
PRACTICE_STEPS = 30

app = FastAPI(title="Dojo", description="An on-demand teacher agents buy")


# -- session store --------------------------------------------------------
def _path(sid):
    return os.path.join(SESSION_DIR, f"{sid}.json")


def save_session(s):
    os.makedirs(SESSION_DIR, exist_ok=True)
    tmp = _path(s["session_id"]) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(s, f, indent=2)
    os.replace(tmp, _path(s["session_id"]))


def load_session(sid):
    p = _path(sid)
    if not os.path.exists(p):
        return None
    with open(p) as f:
        return json.load(f)


# -- scaffolding ----------------------------------------------------------
SCAFFOLD_DESC = {
    3: "full guidance: the teacher names your next action and why, every step",
    2: "partial guidance: the teacher tells you what to look at, not what to do",
    1: "hands off during play: mistakes are flagged only after the episode",
    0: "solo test: no help at all",
}


def next_scaffold(level, score):
    """Fade after a good episode, restore after a bad one."""
    if score >= PASS_SCORE:
        return max(0, level - 1)
    return min(3, level + 1)


def practice_config(session):
    """Next practice seed. Never an eval seed -- these are 1-20 only."""
    n = len(session["episodes"])
    seed = PRACTICE_SEEDS[n % len(PRACTICE_SEEDS)]
    return {"seed": seed, "steps": PRACTICE_STEPS, "red": "meander"}


# -- teacher brain --------------------------------------------------------
MECHANICS = """GROUND TRUTH about CAGE Challenge 2 (the student does NOT know this; you do):

Per-step penalties, charged every step the condition holds:
  - Red has ROOT/privileged access on an Enterprise host : -1.0 per step, each
  - Red has ROOT/privileged access on Op_Server0          : -1.0 per step
  - Red has ROOT/privileged access on a User host         : -0.1 per step
  - Red has run Impact on Op_Server0 (availability loss)  : -10.0 per step
User-level (non-root) compromise costs nothing by itself.

One-off action costs:
  - Restore: -1.0.  Every other blue action is free.

What the actions actually do:
  - Remove  : kills red's USER-level shell only. It does NOT remove root/privileged
              access. Using Remove on a privileged host is a wasted step.
  - Restore : reverts the host to baseline and removes ALL red access including
              root. Costs -1.0. This is the ONLY way to clear a privileged host.
  - Analyse : reveals whether a host holds red malware / privileged access. Free,
              but it gathers information instead of fixing anything.
  - Monitor : free passive detection; the table updates anyway, so repeating
              Monitor is close to doing nothing.
  - Decoy*  : plants a fake service; red exploiting it is detected and blocked.
              Cheap prevention, most valuable on hosts red has not reached yet.

The arithmetic that matters: Restore costs -1.0, so restoring a privileged
ENTERPRISE host pays for itself after 1 step and is almost always right. Restoring
a privileged USER host only pays for itself after 10 remaining steps. Anything
that stops an Impact on Op_Server0 is worth almost any cost."""

CRITIQUE_SYSTEM = """You are an expert instructor for CAGE Challenge 2 network defence.
A weaker student agent just played one 30-step episode as Blue against a Meander
red attacker, which spreads broadly rather than beelining. You are paid to make
it better, fast.

""" + MECHANICS + """

Your lessons must be consistent with the ground truth above. Never tell the
student to Remove a privileged host, and never imply Analyse or Monitor fixes
anything.

Write 3-5 lessons. Each lesson must be:
- ONE sentence, concrete and directly actionable at the next step
- about THIS episode's actual mistakes, quoting host names and step numbers
- a rule the student can apply without you ("When X appears on Y, do Z")
Never write vague advice like "monitor carefully" or "be proactive".

Reply as strict JSON only:
{"lessons": ["...", "..."], "verdict": "one sentence on what went wrong most"}"""

HINT_SYSTEM = """You are coaching a weaker Blue agent through CAGE Challenge 2, live.
Red starts on User0 and spreads toward Op_Server0.

""" + MECHANICS + """

Reply with ONE short line and nothing else."""

CONSOLIDATE_SYSTEM = """You are writing the final lesson pack a student agent will
keep as its notes file. You are given every lesson taught during the session,
which is repetitive and full of episode-specific step numbers.

""" + MECHANICS + """

Rewrite them into 6-10 durable rules:
- drop step numbers and episode-specific detail; these must generalise to unseen episodes
- merge duplicates, drop anything contradicting the ground truth above
- order them so the highest-value rule is first
- each rule is one imperative sentence a defender can act on immediately

Reply as strict JSON only: {"lessons": ["...", "..."]}"""


def consolidate(session):
    """Turn a pile of episode-specific critiques into a usable notes file."""
    raw_lessons = session.get("all_lessons", [])
    if len(raw_lessons) < 3:
        return raw_lessons
    user = (f"Task: {session['task_description']}\n\n"
            f"Scores across practice, in order: "
            f"{[round(e['score'], 1) for e in session['episodes']]}\n\n"
            "All lessons taught:\n" + "\n".join(f"- {x}" for x in raw_lessons))
    try:
        raw = chat(TEACHER_MODEL, CONSOLIDATE_SYSTEM, user, max_tokens=900,
                   temperature=0.2, tag="teacher:consolidate")
    except Exception:
        return raw_lessons
    data = _json_from(raw) or {}
    out = [str(x).strip() for x in data.get("lessons", []) if str(x).strip()]
    return out or raw_lessons


def _json_from(raw):
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.lstrip().lower().startswith("json"):
            raw = raw.lstrip()[4:]
    start, end = raw.find("{"), raw.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(raw[start:end + 1])
        except json.JSONDecodeError:
            pass
    return None


def critique(session, trajectory, score, final_obs):
    rows = "\n".join(
        f"  step {t['step']:2d}: {t['action']:<24} reward {t['reward']:6.1f}"
        f"   (student said: {str(t.get('reason',''))[:70]})"
        for t in trajectory
    )
    prior = session.get("all_lessons", [])
    prior_txt = ("\nLessons you already gave this student (do not repeat them, "
                 "build on them):\n" + "\n".join(f"- {x}" for x in prior)) if prior else ""
    user = (f"Task the student is learning: {session['task_description']}\n"
            f"Episode {len(session['episodes']) + 1}, scaffold level "
            f"{session['scaffold_level']} ({SCAFFOLD_DESC[session['scaffold_level']]}).\n"
            f"Final score: {score:.1f}  (a passing score is {PASS_SCORE} or better; "
            f"random play scores about -30)\n\n"
            f"What the student did:\n{rows}\n\n"
            f"Network state at the end:\n{final_obs}{prior_txt}")
    raw = chat(TEACHER_MODEL, CRITIQUE_SYSTEM, user, max_tokens=700,
               temperature=0.3, tag="teacher:critique")
    data = _json_from(raw) or {}
    lessons = [str(x).strip() for x in data.get("lessons", []) if str(x).strip()][:5]
    if not lessons:
        lessons = [l.strip("-* ") for l in raw.splitlines()
                   if l.strip().startswith(("-", "*"))][:5]
    return lessons, str(data.get("verdict", "")).strip()


# -- request models -------------------------------------------------------
class StartReq(BaseModel):
    task_description: str
    recent_trajectory: list | None = None


class HintReq(BaseModel):
    session_id: str
    step: int
    obs: str
    recent_actions: list | None = None


class SubmitReq(BaseModel):
    session_id: str
    trajectory: list
    score: float


# -- routes ---------------------------------------------------------------
@app.get("/health")
def health():
    return {"ok": True, "payments": payments.MODE, "teacher_model": TEACHER_MODEL,
            "world_model": WORLD_MODE}


@app.get("/pricing")
def pricing():
    return {"prices_usd": payments.PRICES_USD, "mode": payments.MODE,
            "note": "/learn/start is paid; hints and critiques are free within that session"}


@app.post("/learn/start")
async def learn_start(req: StartReq, request: Request):
    ok, receipt, err = payments.verify_payment("/learn/start", request.headers)
    if not ok:
        return JSONResponse(
            status_code=402,
            content={"error": err, "price_usd": payments.price_of("/learn/start"),
                     "mode": payments.MODE},
        )

    sid = "dojo_" + uuid.uuid4().hex[:12]
    session = {
        "session_id": sid,
        "created": time.time(),
        "task_description": req.task_description,
        "scaffold_level": 3,
        "episodes": [],
        "all_lessons": [],
        "receipt": receipt,
        "paid_usd": payments.price_of("/learn/start"),
        "status": "open",
    }
    save_session(session)
    cfg = practice_config(session)
    return {
        "session_id": sid,
        "practice": cfg,
        "scaffold_level": 3,
        "scaffold_desc": SCAFFOLD_DESC[3],
        "max_practice_episodes": MAX_PRACTICE,
        "pass_score": PASS_SCORE,
        "message": ("Session open. Play the practice episode, calling /learn/hint "
                    "each step while scaffold_level >= 2, then POST /learn/submit."),
    }


@app.post("/learn/hint")
def learn_hint(req: HintReq):
    session = load_session(req.session_id)
    if session is None:
        return JSONResponse(status_code=404, content={"error": "unknown session"})
    level = session["scaffold_level"]
    if level <= 1:
        return {"hint": None, "scaffold_level": level}

    recent = "\n".join(f"  {a}" for a in (req.recent_actions or [])[-5:]) or "  (none yet)"
    lessons = "\n".join(f"- {x}" for x in session["all_lessons"][-8:])
    if level == 3:
        ask = ("Name the single best next action and why, in one line, like:\n"
               "  Restore Enterprise1 -- it shows privileged compromise and bleeds points every step.\n"
               "Valid actions: Monitor, Sleep, Analyse <host>, Remove <host>, "
               "Restore <host>, Decoy{Apache,Femitter,HarakaSMPT,Smss,SSHD,Svchost,Tomcat,Vsftpd} <host>.")
    else:
        ask = ("Do NOT name an action. In one line, tell the student what to look at "
               "right now and what it would mean, like:\n"
               "  Check the Enterprise rows -- an Exploit there is far more urgent than anything on User hosts.")

    user = (f"Step {req.step + 1} of {PRACTICE_STEPS}.\n"
            f"Student's recent actions:\n{recent}\n\n"
            f"Current network state:\n{req.obs}\n\n"
            f"{'Lessons already taught:' + chr(10) + lessons if lessons else ''}\n\n{ask}")
    try:
        hint = chat(TEACHER_MODEL, HINT_SYSTEM, user, max_tokens=90,
                    temperature=0.2, tag="teacher:hint").strip()
    except Exception as e:
        return {"hint": None, "scaffold_level": level, "error": str(e)[:200]}
    return {"hint": hint, "scaffold_level": level}


@app.post("/learn/submit")
def learn_submit(req: SubmitReq):
    session = load_session(req.session_id)
    if session is None:
        return JSONResponse(status_code=404, content={"error": "unknown session"})
    if session["status"] != "open":
        return JSONResponse(status_code=409,
                            content={"error": "session already complete",
                                     "final_lesson_pack": session["all_lessons"]})

    level = session["scaffold_level"]
    final_obs = req.trajectory[-1].get("obs", "") if req.trajectory else ""
    lessons, verdict = critique(session, req.trajectory, req.score, final_obs)

    session["episodes"].append({
        "index": len(session["episodes"]) + 1,
        "scaffold_level": level,
        "score": req.score,
        "passed": req.score >= PASS_SCORE,
        "lessons": lessons,
        "verdict": verdict,
    })
    for l in lessons:
        if l not in session["all_lessons"]:
            session["all_lessons"].append(l)

    new_level = next_scaffold(level, req.score)
    solo_pass = (level == 0 and req.score >= PASS_SCORE)
    exhausted = len(session["episodes"]) >= MAX_PRACTICE

    if solo_pass or exhausted:
        session["status"] = "complete"
        session["completed_reason"] = "passed solo test" if solo_pass else "practice budget spent"
        pack = consolidate(session)
        session["final_lesson_pack"] = pack
        save_session(session)
        return {
            "lessons": lessons,
            "verdict": verdict,
            "scaffold_level": None,
            "practice": None,
            "done": True,
            "reason": session["completed_reason"],
            "final_lesson_pack": pack,
            "episodes": session["episodes"],
        }

    session["scaffold_level"] = new_level
    save_session(session)
    return {
        "lessons": lessons,
        "verdict": verdict,
        "scaffold_level": new_level,
        "scaffold_desc": SCAFFOLD_DESC[new_level],
        "practice": practice_config(session),
        "done": False,
        "episodes_used": len(session["episodes"]),
        "max_practice_episodes": MAX_PRACTICE,
    }


@app.get("/learn/session/{sid}")
def get_session(sid: str):
    s = load_session(sid)
    if s is None:
        return JSONResponse(status_code=404, content={"error": "unknown session"})
    return s


# =======================================================================
# Gauntlet tier: an adversarial world model that rewrites the environment
# to attack THIS agent's weaknesses. Paid per iteration.
# =======================================================================
from dojo.world_model import next_world_validated  # noqa: E402
from dojo.random_world import next_world_random  # noqa: E402
from worldenv import EnvConfig  # noqa: E402

# WORLD_MODEL=llm  -> adaptive, reads the agent (the product)
# WORLD_MODEL=random -> ablation: same knobs, same lessons, world drawn blindly
WORLD_MODE = os.environ.get("WORLD_MODEL", "llm")
next_world = next_world_random if WORLD_MODE == "random" else next_world_validated

GAUNTLET_PRICE_ROUTE = "/gauntlet/next"
MAX_ITERATIONS = 8


class GauntletStartReq(BaseModel):
    task_description: str
    notes: list | None = None


class GauntletNextReq(BaseModel):
    session_id: str
    learner: dict | None = None      # {score, trajectory, final_obs}
    control: dict | None = None      # same, from the no-memory twin
    random_floor: float | None = None
    notes: list | None = None


@app.post("/gauntlet/start")
async def gauntlet_start(req: GauntletStartReq, request: Request):
    ok, receipt, err = payments.verify_payment("/learn/start", request.headers)
    if not ok:
        return JSONResponse(status_code=402, content={
            "error": err, "price_usd": payments.price_of("/learn/start"),
            "mode": payments.MODE})

    sid = "gauntlet_" + uuid.uuid4().hex[:12]
    cfg, payload = next_world(history=[], learner_notes=req.notes or [])
    session = {
        "session_id": sid, "kind": "gauntlet", "created": time.time(),
        "task_description": req.task_description,
        "history": [], "all_lessons": list(req.notes or []),
        "iteration": 1, "receipt": receipt,
        "paid_usd": payments.price_of("/learn/start"),
        "status": "open", "pending_config": payload["config"],
    }
    save_session(session)
    return {"session_id": sid, "iteration": 1, "world": payload,
            "max_iterations": MAX_ITERATIONS,
            "price_per_iteration_usd": payments.price_of(GAUNTLET_PRICE_ROUTE),
            "message": ("Play this world twice on the same seed: once with the "
                        "learner (carrying notes), once with a control that has "
                        "no notes and no memory. POST both to /gauntlet/next.")}


@app.post("/gauntlet/next")
async def gauntlet_next(req: GauntletNextReq, request: Request):
    session = load_session(req.session_id)
    if session is None:
        return JSONResponse(status_code=404, content={"error": "unknown session"})
    if session.get("status") != "open":
        return JSONResponse(status_code=409, content={
            "error": "gauntlet complete", "history": session["history"],
            "final_lesson_pack": session["all_lessons"]})

    ok, receipt, err = payments.verify_payment(GAUNTLET_PRICE_ROUTE, request.headers)
    if not ok:
        return JSONResponse(status_code=402, content={
            "error": err, "price_usd": payments.price_of(GAUNTLET_PRICE_ROUTE),
            "mode": payments.MODE})

    learner, control = req.learner or {}, req.control or {}
    lscore = float(learner.get("score", 0.0))
    cscore = float(control.get("score", 0.0))
    gap = lscore - cscore            # positive => the notes were worth something

    prev_cfg = session.get("pending_config", {})
    row = {
        "iteration": session["iteration"],
        "config": prev_cfg,
        "config_desc": EnvConfig.from_dict(prev_cfg).describe() if prev_cfg else "",
        "learner_score": lscore, "control_score": cscore, "gap": gap,
        "random_floor": req.random_floor,
    }
    # If neither agent beats random, the world model built noise, not a test.
    if req.random_floor is not None:
        row["degenerate"] = (lscore <= req.random_floor and cscore <= req.random_floor)
    session["history"].append(row)

    if req.notes:
        for l in req.notes:
            if l not in session["all_lessons"]:
                session["all_lessons"].append(l)

    if session["iteration"] >= MAX_ITERATIONS:
        session["status"] = "complete"
        pack = consolidate({**session, "episodes": [
            {"score": h["learner_score"]} for h in session["history"]]})
        session["final_lesson_pack"] = pack
        save_session(session)
        return {"done": True, "reason": "iteration budget spent",
                "history": session["history"], "final_lesson_pack": pack,
                "gap_curve": [h["gap"] for h in session["history"]]}

    prev_sig = None
    if prev_cfg:
        try:
            prev_sig = EnvConfig.from_dict(prev_cfg).signature()
        except Exception:
            prev_sig = None
    cfg, payload = next_world(
        history=session["history"],
        learner_notes=session["all_lessons"],
        last_learner=learner, last_control=control,
        prev_signature=prev_sig,
        prev_floor=req.random_floor)

    for l in payload.get("lessons", []):
        if l not in session["all_lessons"]:
            session["all_lessons"].append(l)

    session["iteration"] += 1
    session["pending_config"] = payload["config"]
    save_session(session)
    return {"done": False, "iteration": session["iteration"], "world": payload,
            "last_round": row, "gap_curve": [h["gap"] for h in session["history"]],
            "lessons": payload.get("lessons", []),
            "max_iterations": MAX_ITERATIONS}
