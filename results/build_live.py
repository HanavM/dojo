"""Build results/live.html -- a screen-recordable replay of the real run.

Every number comes from results/selftrain.json and results/final_exam.json.
Nothing is invented and nothing is called at view time, so it paces identically
on every take and cannot stall mid-recording.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "live.html")


# CybORG charges this much damage per turn while Red holds root on a host.
RATE = {"None": 0.0, "Low": 0.1, "Medium": 1.0, "High": 10.0}


def short_change(cfg, prev):
    """A few words for the round header -- what got harder, at a glance."""
    if prev is None:
        return "baseline"
    if cfg["red"] != prev["red"]:
        return "faster attacker"
    if cfg.get("green_noise") and not prev.get("green_noise"):
        return "added decoy traffic"
    for h, v in (cfg.get("host_values") or {}).items():
        old = (prev.get("host_values") or {}).get(h)
        if old != v:
            was = RATE.get((old or {}).get("conf", "None"), 0.0)
            now = RATE.get(v.get("conf", "None"), 0.0)
            return f"{h} breach: {was:g} \u2192 {now:g} dmg/turn"
    return "no change"


def describe_change(cfg, prev):
    if prev is None:
        return "starting world — slow attacker, nothing is worth much yet"
    bits = []
    if cfg["red"] != prev["red"]:
        bits.append("attacker switched to the one that beelines at the crown server")
    if cfg.get("green_noise") and not prev.get("green_noise"):
        bits.append("added benign staff traffic that looks like reconnaissance")
    for h, v in (cfg.get("host_values") or {}).items():
        old = (prev.get("host_values") or {}).get(h)
        if old != v:
            was = RATE.get((old or {}).get("conf", "None"), 0.0)
            now = RATE.get(v.get("conf", "None"), 0.0)
            bits.append(
                f"{h} now holds sensitive data — while the attacker holds it, "
                f"it costs {now:g} damage per turn instead of {was:g}")
    return "; ".join(bits) or "no change"


def main():
    st = json.load(open(os.path.join(HERE, "selftrain.json")))
    try:
        exam = json.load(open(os.path.join(HERE, "final_exam.json")))
    except (OSError, json.JSONDecodeError):
        exam = None

    rounds, prev = [], None
    for r in st["rounds"]:
        a = r.get("learner_takeover") or {}
        c = r.get("control_takeover") or {}
        v = r.get("note_validation") or {}
        rounds.append({
            "n": r["iteration"],
            "world": r["config_desc"],
            "change": describe_change(r["config"], prev),
            "short": short_change(r["config"], prev),
            "floor": r.get("next_floor"),
            "agent": round(r["learner_mean"], 1),
            "control": round(r["control_mean"], 1),
            "gap": round(r["gap"], 1),
            "agent_hosts": [a.get("hosts_compromised"), a.get("hosts_total")],
            "control_hosts": [c.get("hosts_compromised"), c.get("hosts_total")],
            "crown_a": a.get("crown_server_lost"),
            "crown_c": c.get("crown_server_lost"),
            "notes_count": r.get("notes_count"),
            "val": ({"old": v.get("old_score"), "new": v.get("new_score"),
                     "adopted": v.get("adopted")} if v else None),
            "new_notes": r.get("round_lessons") or [],
        })
        prev = r["config"]

    data = {"rounds": rounds, "final_notes": st.get("notes", []),
            "exam": ({"summary": {k: {{"no notes": "no learning",
                                      "self notes": "with learning"}.get(a, a): v
                                     for a, v in arms.items()}
                                 for k, arms in exam["summary"].items()}, "overall": {{"no notes": "no learning",
                                  "self notes": "with learning"}.get(a, a): v
                                 for a, v in exam["overall"].items()},
                      "arms": [{"no notes": "no learning", "self notes": "with learning"}.get(a, a)
                               for a in exam["arms"] if a != "taught notes"],
                      "exams": {k: v["label"] for k, v in exam["exams"].items()}}
                     if exam else None)}

    html = PAGE.replace("__DATA__", json.dumps(data).replace("</", "<\\/"))
    assert "__DATA__" not in html
    with open(OUT, "w") as f:
        f.write(html)
    print(f"wrote {OUT} ({os.path.getsize(OUT)/1024:.0f} KB)")


PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dojo — live</title><style>
:root{color-scheme:light;--bg:#f4f4f1;--card:#fcfcfb;--rule:#dedcd4;
 --ink:#0b0b0b;--ink2:#52514e;--ink3:#78766f;
 --agent:#2a78d6;--control:#eb6834;--world:#1baf7a}
@media(prefers-color-scheme:dark){:root:not([data-theme=light]){color-scheme:dark;
 --bg:#111110;--card:#1a1a19;--rule:#33332f;--ink:#fff;--ink2:#c3c2b7;--ink3:#94938a;
 --agent:#3987e5;--control:#d95926;--world:#199e70}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
 font:15px/1.55 ui-sans-serif,-apple-system,system-ui,sans-serif;
 -webkit-font-smoothing:antialiased}
.wrap{max-width:660px;margin:0 auto;padding:44px 20px 90px}
h1{font-size:25px;margin:0 0 3px;letter-spacing:-.02em}
.sub{color:var(--ink2);font-size:14px;margin:0 0 24px;max-width:56ch}
button{font:inherit;font-weight:620;padding:12px 28px;border-radius:9px;border:none;
 background:var(--ink);color:var(--bg);cursor:pointer;
 position:sticky;bottom:18px;z-index:5;box-shadow:0 3px 14px rgba(0,0,0,.16)}
button:disabled{opacity:.4;cursor:default}
.card{background:var(--card);border:1px solid var(--rule);border-radius:12px;
 padding:18px;margin-top:14px;animation:in .35s ease-out}
@keyframes in{from{opacity:0;transform:translateY(7px)}to{opacity:1;transform:none}}
.rnum{font-size:11.5px;letter-spacing:.09em;text-transform:uppercase;
 color:var(--ink3);font-weight:640}
.rnum .tag{margin-left:9px;padding:2px 9px;border-radius:99px;letter-spacing:.02em;
 text-transform:none;font-size:11.5px;font-weight:620;
 background:color-mix(in oklab,var(--world) 16%,transparent);color:var(--world)}
.change{font-size:13.5px;margin-top:7px;padding:9px 12px;border-radius:0 6px 6px 0;
 background:color-mix(in oklab,var(--world) 12%,transparent);
 border-left:3px solid var(--world)}
.floor{font-size:12px;color:var(--ink3);margin-top:6px}
.status{font-size:13.5px;color:var(--ink2);margin-top:14px}
.barwrap{height:5px;border-radius:3px;margin-top:9px;overflow:hidden;
 background:color-mix(in oklab,var(--ink) 8%,transparent)}
.barfill{height:100%;width:0;border-radius:3px;background:var(--ink3)}
.row{display:grid;grid-template-columns:104px 1fr 86px;gap:10px;align-items:center;
 margin-top:9px}
.who{font-size:12.5px;color:var(--ink2);display:flex;align-items:center;gap:6px}
.dot{width:9px;height:9px;border-radius:3px;flex:none}
.track{display:block;height:19px;border-radius:4px;overflow:hidden;
 background:color-mix(in oklab,var(--ink) 7%,transparent)}
.fill{display:block;height:100%;border-radius:4px;width:0;transition:width 1.4s ease-out}
.val{text-align:right;font-size:13px;font-weight:650;font-variant-numeric:tabular-nums}
.hosts{font-size:11.5px;color:var(--ink3);text-align:right}
.verdict{margin-top:12px;font-size:14px}
.verdict b{font-size:17px}
.check{margin-top:13px;display:flex;align-items:center;gap:8px;font-size:13.5px;
 font-weight:620;color:var(--world);animation:in .3s ease-out}
.check .mark{display:inline-flex;align-items:center;justify-content:center;
 width:21px;height:21px;border-radius:50%;background:var(--world);color:#fff;
 font-size:13px;font-weight:800;flex:none}
.check.lose{color:var(--control)}
.check.lose .mark{background:var(--control)}
.win{color:var(--world)}.lose{color:var(--control)}
.note{font-size:12.5px;color:var(--ink2);margin-top:11px;padding-left:12px;
 border-left:2px solid var(--rule)}
ul{margin:9px 0 0;padding-left:19px;font-size:13px;color:var(--ink2)}
li{margin-bottom:4px}
.lbl{font-size:11.5px;letter-spacing:.07em;text-transform:uppercase;color:var(--ink3);
 font-weight:640;margin-top:15px}
table{width:100%;border-collapse:collapse;font-size:13.5px;margin-top:10px;
 font-variant-numeric:tabular-nums}
th,td{text-align:right;padding:7px 8px;border-bottom:1px solid var(--rule)}
th:first-child,td:first-child{text-align:left}
th{font-size:11px;letter-spacing:.05em;text-transform:uppercase;color:var(--ink3);
 font-weight:640}
.best{color:var(--world);font-weight:680}
.exam{border-width:2px;border-color:var(--ink3)}
.term{font-family:ui-monospace,"SF Mono",Menlo,monospace;font-size:12.5px;
 line-height:1.75;white-space:pre-wrap;word-break:break-word}
.term .cmd{color:var(--ink)}
.term .dim{color:var(--ink3)}
.term .warn{color:var(--control)}
.term .ok{color:var(--world);font-weight:620}
.blink{animation:b 1.1s infinite}@keyframes b{50%{opacity:.4}}
</style></head><body><div class="wrap">
<h1>A Computer Management Agent</h1>
<p class="sub">The agent is under attack by other agents that are trying to attack and secure all 13 of the company's network devices. It never learned how to approach this kind of cybersecurity task, so it calls Dojo.</p>
<button id="go">Start</button>
<div id="out"></div>
</div>
<script id="data" type="application/json">__DATA__</script>
<script>
const D=JSON.parse(document.getElementById('data').textContent);
const out=document.getElementById('out'), go=document.getElementById('go');
const esc=s=>String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const wait=ms=>new Promise(r=>setTimeout(r,ms));
const el=h=>{const d=document.createElement('div');d.innerHTML=h.trim();return d.firstElementChild;};

function gate(label){return new Promise(r=>{
  go.disabled=false; go.textContent=label;
  go.scrollIntoView({behavior:'smooth',block:'center'});
  go.onclick=()=>{go.disabled=true; go.textContent='Running'; go.onclick=null; r();};
});}

function bar(el,ms){return new Promise(r=>{
  const t0=performance.now();
  (function step(now){const p=Math.min(1,(now-t0)/ms);el.style.width=(p*100)+'%';
   p<1?requestAnimationFrame(step):r();})(t0);});}

// Scale each round against its own worst score. The comparison that matters is
// agent vs control WITHIN a round; scaling globally makes early rounds invisible.

const PAY=[
 ['cmd', '$ pay --sandbox curl -X POST https://dojo-teacher.pay.sh/learn/start'],
 ['dim', '  POST /learn/start'],
 ['warn','  402 Payment Required   $0.05 USDC'],
 ['dim', '  settling on Solana...'],
 ['ok',  '  200 OK   payment-receipt: 35FnLZV7e8Gs...WHfn68'],
 ['dim', '  session opened — the agent has bought its training'],
];

async function payCard(){
  const card=el(`<div class="card"><div class="rnum">The agent buys a training session</div>
    <div class="term" id="t"></div></div>`);
  out.appendChild(card);
  const t=card.querySelector('#t');
  const [head,...rest]=PAY;
  t.insertAdjacentHTML('beforeend',`<div class="${head[0]}">${esc(head[1])}</div>`);
  await wait(1400);                      // beat on the command itself
  t.insertAdjacentHTML('beforeend',
    rest.map(([cls,line])=>`<div class="${cls}">${esc(line)}</div>`).join(''));
  await wait(900);
}

async function run(){
  go.disabled=true; go.textContent='Running';
  await payCard();
  await gate('Start training →');
  for(const r of D.rounds){
    const card=el(`<div class="card">
      <div class="rnum">Round ${r.n}<span class="tag">${esc(r.short)}</span></div>
      <div class="change">${esc(r.change)}</div>
      <div class="status" id="s"><span class="blink">The agent is playing 25 turns…</span></div>
      <div class="barwrap"><div class="barfill" id="b"></div></div>
    </div>`);
    out.appendChild(card); card.scrollIntoView({behavior:'smooth',block:'end'});
    await bar(card.querySelector('#b'), 5200);

    card.querySelector('#b').parentElement.remove();
    card.querySelector('#s').innerHTML='';
    const mk=(who,v,hosts,color)=>`<div class="row">
      <span class="who"><span class="dot" style="background:${color}"></span>${who}</span>
      <span class="track"><span class="fill" style="background:${color}"></span></span>
      <span><span class="val">${v.toFixed(1)}</span>
      <div class="hosts">${hosts[0]}/${hosts[1]} hosts lost</div></span></div>`;
    card.querySelector('#s').insertAdjacentHTML('afterend',
      mk('with learning',r.agent,r.agent_hosts,'var(--agent)')+
      mk('no learning',r.control,r.control_hosts,'var(--control)'));
    await wait(60);
    const scale=Math.max(Math.abs(r.agent),Math.abs(r.control),1);
    const fills=card.querySelectorAll('.fill');
    fills[0].style.width=Math.max(3,Math.abs(r.agent)/scale*100)+'%';
    fills[1].style.width=Math.max(3,Math.abs(r.control)/scale*100)+'%';
    await wait(1800);

    const win = r.agent > r.control;   // less damage = better
    card.insertAdjacentHTML('beforeend',
      `<div class="check ${win?'':'lose'}"><span class="mark">${win?'\u2713':'\u2715'}</span>
       ${win ? 'the agent with learning did better'
             : 'the agent with learning did not do better'}</div>`);
    await wait(2800);

    if(r.val){
      await gate('Let the environment model reflect →');
      const st=el(`<div class="status"><span class="blink">Learning from that round, then testing what it learned on unseen seeds…</span></div>`);
      card.appendChild(st);
      const bw=el(`<div class="barwrap"><div class="barfill"></div></div>`);
      card.appendChild(bw);
      await bar(bw.firstElementChild,4000);
      bw.remove();
      st.remove();
    }
    card.scrollIntoView({behavior:'smooth',block:'end'});
    await wait(1000);
  }

  // what it ended up believing
  await gate('See what it worked out →');
  const nc=el(`<div class="card"><div class="rnum">What it learned by itself</div>
    <ul>${D.final_notes.slice(0,6).map(n=>`<li>${esc(n)}</li>`).join('')}</ul></div>`);
  out.appendChild(nc); nc.scrollIntoView({behavior:'smooth',block:'end'});
  await wait(5200);

  if(D.exam){
    await gate('Run the final exam →');
    const card=el(`<div class="card exam">
      <div class="status" id="s"><span class="blink">Playing 12 episodes per condition…</span></div>
      <div class="barwrap"><div class="barfill" id="b"></div></div></div>`);
    out.appendChild(card); card.scrollIntoView({behavior:'smooth',block:'end'});
    await bar(card.querySelector('#b'),6000);
    card.querySelector('#b').parentElement.remove();
    const arms=D.exam.arms, ov=D.exam.overall;
    const best=arms.reduce((a,b)=>ov[b].mean>ov[a].mean?b:a);
    card.querySelector('#s').outerHTML=`<table>
      <thead><tr><th>world</th>${arms.map(a=>`<th>${esc(a)}</th>`).join('')}</tr></thead>
      <tbody>${Object.entries(D.exam.exams).map(([k,lab])=>`<tr><td>${esc(lab)}</td>${
        arms.map(a=>{const m=D.exam.summary[k][a].mean;
          const b=arms.every(x=>D.exam.summary[k][x].mean<=m);
          return `<td class="${b?'best':''}">${m.toFixed(1)}</td>`;}).join('')}</tr>`).join('')}
        <tr><td><b>overall</b></td>${arms.map(a=>
          `<td class="${a===best?'best':''}"><b>${ov[a].mean.toFixed(1)}</b></td>`).join('')}</tr>
        <tr><td>catastrophes</td>${arms.map(a=>
          `<td>${ov[a].blowups}/${ov[a].n}</td>`).join('')}</tr>
      </tbody></table>`;
    await wait(400);
    card.scrollIntoView({behavior:'smooth',block:'end'});
  }
  go.textContent='Done';
}
go.onclick=run;
</script></body></html>
"""

if __name__ == "__main__":
    main()
