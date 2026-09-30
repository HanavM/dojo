"""Live demo: press Start, watch the loop run for real.

Nothing here is replayed from a file. Every turn you see is an actual model call
against the actual simulator, streamed over SSE as it happens.

  uvicorn dojo.live_demo:app --port 8090
"""
import asyncio
import json
import queue
import sys
import threading

sys.path.insert(0, "/Users/hanavmodasiya/trainme")
sys.path.insert(0, "/Users/hanavmodasiya/trainme/cage")

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse

from worldenv import EnvConfig, WorldEnv
from dojo.agent import BlueAgent
from dojo.world_model import next_world_validated

app = FastAPI(title="Dojo live")

ROUNDS = 3
SEED = 501
STEPS = 20          # short enough to watch, long enough for Red to get moving

# The exam: a fixed hard world, never trained on, agent keeps every tool.
EXAM_CFG = dict(red="bline", steps=20)
EXAM_SEED = 700


def play(agent, cfg, seed, emit, who):
    """One episode, emitting every turn as it happens."""
    env = WorldEnv(cfg)
    obs = env.reset(seed)
    traj = []
    for step in range(cfg.steps):
        action, why = agent.act(env, obs, traj, step, tag=f"live:{who}")
        obs, reward, done, _ = env.step(action)
        traj.append({"step": step + 1, "action": action, "reason": why,
                     "reward": reward, "cumulative": env.total_reward,
                     "obs": obs})
        emit({"type": "turn", "who": who, "step": step + 1,
              "action": action, "damage": round(env.total_reward, 1)})
        if done:
            break
    return {"score": env.total_reward, "trajectory": traj,
            "final_obs": traj[-1]["obs"] if traj else ""}


def loop(emit):
    notes = []
    history = []
    cfg, world = next_world_validated([], [])
    for rnd in range(1, ROUNDS + 1):
        cfg.steps = STEPS
        emit({"type": "round", "n": rnd, "total": ROUNDS,
              "world": cfg.describe(),
              "diagnosis": world.get("diagnosis", "")})

        emit({"type": "playing", "who": "learner"})
        L = play(BlueAgent(notes="\n".join(f"- {x}" for x in notes),
                           name="learner"), cfg, SEED, emit, "learner")
        emit({"type": "playing", "who": "control"})
        C = play(BlueAgent(notes="", name="control"), cfg, SEED, emit, "control")

        emit({"type": "scores", "round": rnd,
              "learner": round(L["score"], 1), "control": round(C["score"], 1)})

        if rnd == ROUNDS:
            break

        emit({"type": "thinking"})
        history.append({"iteration": rnd, "gap": L["score"] - C["score"],
                        "learner_score": L["score"], "control_score": C["score"],
                        "config_desc": cfg.describe()})
        cfg, world = next_world_validated(history, notes, L, C,
                                          prev_signature=cfg.signature())
        new = [x for x in world.get("lessons", []) if x not in notes]
        notes.extend(new)
        emit({"type": "notes", "lessons": new})

    # ---- post-training: a fixed hard world neither agent has seen ----
    exam = EnvConfig.from_dict(EXAM_CFG)
    emit({"type": "exam", "world": exam.describe(), "notes_count": len(notes)})

    emit({"type": "playing", "who": "learner"})
    EL = play(BlueAgent(notes="\n".join(f"- {x}" for x in notes),
                        name="exam-learner"), exam, EXAM_SEED, emit, "learner")
    emit({"type": "playing", "who": "control"})
    EC = play(BlueAgent(notes="", name="exam-control"), exam, EXAM_SEED,
              emit, "control")
    emit({"type": "scores", "round": "exam",
          "learner": round(EL["score"], 1), "control": round(EC["score"], 1)})
    emit({"type": "done"})


@app.get("/stream")
def stream():
    q = queue.Queue()

    def emit(ev):
        q.put(ev)

    def run():
        try:
            loop(emit)
        except Exception as e:
            q.put({"type": "error", "message": f"{type(e).__name__}: {e}"})
        q.put(None)

    threading.Thread(target=run, daemon=True).start()

    async def gen():
        while True:
            ev = await asyncio.to_thread(q.get)
            if ev is None:
                break
            yield f"data: {json.dumps(ev)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dojo — live</title><style>
:root{color-scheme:light;--bg:#f4f4f1;--card:#fcfcfb;--rule:#dedcd4;
 --ink:#0b0b0b;--ink2:#52514e;--ink3:#78766f;
 --learner:#2a78d6;--control:#eb6834;--world:#1baf7a}
@media(prefers-color-scheme:dark){:root:not([data-theme=light]){color-scheme:dark;
 --bg:#111110;--card:#1a1a19;--rule:#33332f;--ink:#fff;--ink2:#c3c2b7;--ink3:#94938a;
 --learner:#3987e5;--control:#d95926;--world:#199e70}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
 font:15px/1.5 ui-sans-serif,-apple-system,system-ui,sans-serif}
.wrap{max-width:660px;margin:0 auto;padding:40px 20px 70px}
h1{font-size:24px;margin:0 0 4px;letter-spacing:-.02em}
.sub{color:var(--ink3);font-size:13.5px;margin:0 0 22px}
button{font:inherit;font-weight:620;padding:11px 26px;border-radius:9px;
 border:none;background:var(--ink);color:var(--bg);cursor:pointer}
button:disabled{opacity:.45;cursor:default}
.card{background:var(--card);border:1px solid var(--rule);border-radius:12px;
 padding:18px;margin-top:16px}
.rnum{font-size:11.5px;letter-spacing:.09em;text-transform:uppercase;
 color:var(--ink3);font-weight:640}
.world{font-family:ui-monospace,Menlo,monospace;font-size:12.5px;margin-top:8px;
 background:color-mix(in oklab,var(--world) 12%,transparent);
 border-left:3px solid var(--world);padding:8px 11px;border-radius:0 6px 6px 0}
.now{font-size:13px;color:var(--ink2);margin-top:12px;min-height:20px}
.turn{font-family:ui-monospace,Menlo,monospace;font-size:12.5px}
.row{display:grid;grid-template-columns:92px 1fr 62px;gap:10px;align-items:center;
 margin-top:8px}
.who{font-size:12.5px;color:var(--ink2);display:flex;align-items:center;gap:6px}
.dot{width:9px;height:9px;border-radius:3px;flex:none}
.track{display:block;height:18px;border-radius:4px;overflow:hidden;
 background:color-mix(in oklab,var(--ink) 7%,transparent)}
.fill{display:block;height:100%;border-radius:4px;transition:width .25s}
.val{text-align:right;font-size:13px;font-weight:650;font-variant-numeric:tabular-nums}
ul{margin:10px 0 0;padding-left:19px;font-size:13px;color:var(--ink2)}
li{margin-bottom:4px}
.lbl{font-size:11.5px;letter-spacing:.07em;text-transform:uppercase;
 color:var(--ink3);font-weight:640;margin-top:14px}
.blink{animation:b 1s infinite}@keyframes b{50%{opacity:.35}}
.exam{border-color:var(--ink3);border-width:2px}
</style></head><body><div class="wrap">
<h1>Watch it learn</h1>
<p class="sub">Blue keeps notes. Orange has none. Same world, same seed.</p>
<button id="go">Start</button>
<div id="out"></div>
</div><script>
const out=document.getElementById('out'), go=document.getElementById('go');
let card=null, max=1;
const esc=s=>String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
function bar(who,color,id){return `<div class="row">
 <span class="who"><span class="dot" style="background:${color}"></span>${who}</span>
 <span class="track"><span class="fill" id="f${id}" style="width:0%;background:${color}"></span></span>
 <span class="val" id="v${id}">0.0</span></div>`}
go.onclick=()=>{
 go.disabled=true; go.textContent='Running';
 const es=new EventSource('/stream');
 es.onmessage=e=>{
  const d=JSON.parse(e.data);
  if(d.type==='exam'){
    card=document.createElement('div'); card.className='card exam';
    card.innerHTML=`<div class="rnum">Exam — a world it never trained on</div>
      <div class="world">${esc(d.world)}</div>
      <div class="now" id="now"></div>
      ${bar('keeps notes','var(--learner)','L')}
      ${bar('no notes','var(--control)','C')}`;
    out.appendChild(card); max=1;
  }
  if(d.type==='round'){
    card=document.createElement('div'); card.className='card';
    card.innerHTML=`<div class="rnum">Round ${d.n} of ${d.total}</div>
      <div class="world">${esc(d.world)}</div>
      <div class="now" id="now"></div>
      ${bar('keeps notes','var(--learner)','L')}
      ${bar('no notes','var(--control)','C')}`;
    out.appendChild(card); max=1;
  }
  if(d.type==='playing'&&card) card.querySelector('#now').innerHTML=
    `<span class="blink">${d.who==='learner'?'Blue':'Orange'} is playing…</span>`;
  if(d.type==='turn'&&card){
    const k=d.who==='learner'?'L':'C';
    max=Math.max(max,Math.abs(d.damage));
    card.querySelector('#now').innerHTML=
      `<span class="turn">turn ${d.step} · ${esc(d.action)}</span>`;
    card.querySelector('#f'+k).style.width=Math.min(100,Math.abs(d.damage)/max*100)+'%';
    card.querySelector('#v'+k).textContent=d.damage.toFixed(1);
    ['L','C'].forEach(x=>{const v=parseFloat(card.querySelector('#v'+x).textContent);
      card.querySelector('#f'+x).style.width=Math.min(100,Math.abs(v)/max*100)+'%';});
  }
  if(d.type==='scores'&&card){
    const g=d.learner-d.control;
    card.querySelector('#now').innerHTML=
      `<b>${Math.abs(g).toFixed(1)} ${g>0?'less':'more'}</b> damage with notes`;
  }
  if(d.type==='thinking'&&card){
    const p=document.createElement('div'); p.className='now blink';
    p.textContent='Watching that game, writing the next lesson…'; card.appendChild(p);
  }
  if(d.type==='notes'&&card){
    card.querySelectorAll('.blink').forEach(x=>x.remove());
    if(d.lessons.length) card.insertAdjacentHTML('beforeend',
      `<div class="lbl">Learned</div><ul>${d.lessons.map(l=>`<li>${esc(l)}</li>`).join('')}</ul>`);
  }
  if(d.type==='error'){out.insertAdjacentHTML('beforeend',
    `<div class="card">Error: ${esc(d.message)}</div>`); es.close(); go.textContent='Failed';}
  if(d.type==='done'){es.close(); go.textContent='Done'; }
 };
 es.onerror=()=>{es.close(); if(go.textContent==='Running')go.textContent='Disconnected';};
};
</script></body></html>"""


@app.get("/", response_class=HTMLResponse)
def index():
    return PAGE
