"""Build results/index.html -- a single static file with results.json inlined.

Inlined rather than fetched so the page opens from file:// with no server.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(HERE, "results.json")
OUT = os.path.join(HERE, "index.html")

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Dojo — results</title>
<style>
  :root{
    color-scheme: light;
    --surface-0:#f4f4f1; --surface-1:#fcfcfb; --surface-2:#eceae4;
    --text-primary:#0b0b0b; --text-secondary:#52514e; --text-muted:#78766f;
    --rule:#dedcd4;
    --series-1:#2a78d6; --series-2:#eb6834; --series-3:#1baf7a;
    --accent:#4a3aa7;
  }
  @media (prefers-color-scheme: dark){
    :root:not([data-theme="light"]){
      color-scheme: dark;
      --surface-0:#111110; --surface-1:#1a1a19; --surface-2:#232321;
      --text-primary:#ffffff; --text-secondary:#c3c2b7; --text-muted:#94938a;
      --rule:#33332f;
      --series-1:#3987e5; --series-2:#d95926; --series-3:#199e70;
      --accent:#9085e9;
    }
  }
  :root[data-theme="dark"]{
    color-scheme: dark;
    --surface-0:#111110; --surface-1:#1a1a19; --surface-2:#232321;
    --text-primary:#ffffff; --text-secondary:#c3c2b7; --text-muted:#94938a;
    --rule:#33332f;
    --series-1:#3987e5; --series-2:#d95926; --series-3:#199e70;
    --accent:#9085e9;
  }
  *{box-sizing:border-box}
  body{
    margin:0; background:var(--surface-0); color:var(--text-primary);
    font:15px/1.55 ui-sans-serif,-apple-system,"SF Pro Text",Inter,system-ui,sans-serif;
    -webkit-font-smoothing:antialiased;
  }
  .wrap{max-width:1040px; margin:0 auto; padding:0 20px 80px}
  header{padding-block:56px 36px; border-bottom:1px solid var(--rule); margin-bottom:36px}
  .eyebrow{font-size:12px; letter-spacing:.1em; text-transform:uppercase;
           color:var(--text-muted); font-weight:600}
  h1{font-size:clamp(30px,5vw,46px); line-height:1.08; margin:14px 0 10px;
     letter-spacing:-.025em; font-weight:660}
  h1 em{font-style:normal; color:var(--accent)}
  .sub{color:var(--text-secondary); max-width:62ch; font-size:16px; margin:0}
  h2{font-size:13px; letter-spacing:.09em; text-transform:uppercase;
     color:var(--text-muted); font-weight:640; margin:0 0 6px}
  .sect{margin-block:44px}
  .sect-note{color:var(--text-secondary); font-size:14px; margin:0 0 22px; max-width:66ch}
  .card{background:var(--surface-1); border:1px solid var(--rule);
        border-radius:12px; padding:24px}
  .tiles{display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
         gap:12px; margin-bottom:8px}
  .tile{background:var(--surface-1); border:1px solid var(--rule);
        border-radius:12px; padding:16px 18px}
  .tile .k{font-size:11.5px; letter-spacing:.07em; text-transform:uppercase;
           color:var(--text-muted); font-weight:620}
  .tile .v{font-size:26px; font-weight:670; letter-spacing:-.02em; margin-top:5px;
           font-variant-numeric:tabular-nums}
  .tile .n{font-size:12.5px; color:var(--text-secondary); margin-top:3px}
  svg{display:block; width:100%; height:auto; overflow:visible}
  .grid-line{stroke:var(--rule); stroke-width:1}
  .axis-text{fill:var(--text-muted); font-size:11.5px; font-variant-numeric:tabular-nums}
  /* halo so the value stays legible where it overlaps an episode dot */
  .bar-label{fill:var(--text-primary); font-size:13px; font-weight:650;
             font-variant-numeric:tabular-nums;
             paint-order:stroke; stroke:var(--surface-1); stroke-width:3.5px;
             stroke-linejoin:round}
  .cond-label{fill:var(--text-primary); font-size:13px; font-weight:600}
  .cond-sub{fill:var(--text-muted); font-size:11.5px}
  .legend{display:flex; flex-wrap:wrap; gap:16px; margin:0 0 18px; padding:0; list-style:none}
  .legend li{display:flex; align-items:center; gap:7px; font-size:13px;
             color:var(--text-secondary)}
  .swatch{width:11px; height:11px; border-radius:3px; flex:none}
  table{width:100%; border-collapse:collapse; font-size:13.5px;
        font-variant-numeric:tabular-nums}
  th,td{text-align:right; padding:8px 10px; border-bottom:1px solid var(--rule)}
  th:first-child,td:first-child{text-align:left}
  th{font-size:11.5px; letter-spacing:.06em; text-transform:uppercase;
     color:var(--text-muted); font-weight:620}
  .scroll{overflow-x:auto}
  ol.lessons{margin:0; padding-left:22px}
  ol.lessons li{margin-bottom:9px; color:var(--text-primary)}
  .two{display:grid; grid-template-columns:1fr 1fr; gap:18px}
  @media (max-width:760px){ .two{grid-template-columns:1fr} }
  .replay{font-family:ui-monospace,"SF Mono",Menlo,monospace; font-size:12.5px}
  .replay tr.good td{background:color-mix(in oklab,var(--series-3) 9%,transparent)}
  .replay tr.bad td{background:color-mix(in oklab,var(--series-2) 11%,transparent)}
  .hint{color:var(--text-secondary); font-style:italic}
  .pill{display:inline-block; padding:2px 8px; border-radius:99px; font-size:11px;
        font-weight:640; background:var(--surface-2); color:var(--text-secondary)}
  .caveat{border-left:3px solid var(--series-2); padding:10px 0 10px 14px;
          color:var(--text-secondary); font-size:13.5px; margin:22px 0 0}
  footer{margin-top:56px; padding-top:22px; border-top:1px solid var(--rule);
         color:var(--text-muted); font-size:12.5px}
  code{background:var(--surface-2); padding:1.5px 5px; border-radius:4px; font-size:12.5px}
</style>
</head>
<body>
<div class="wrap">
<header>
  <div class="eyebrow">Solana hackathon · build something an agent would buy</div>
  <h1>Dojo — an on-demand teacher <em>agents buy</em></h1>
  <p class="sub">An agent meets an unfamiliar task, pays $0.05 over pay.sh for a
  learning session, practises against a teacher whose help fades as it improves,
  and walks away with a notes file. No fine-tuning — learning is written notes
  read before acting.</p>
</header>
<div id="app"></div>
<footer id="foot"></footer>
</div>

<script id="data" type="application/json">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
const COND = ['A','B','C'];
const HUE  = {A:'var(--series-1)', B:'var(--series-2)', C:'var(--series-3)'};
const esc = s => String(s).replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const el = h => { const d=document.createElement('div'); d.innerHTML=h.trim(); return d.firstElementChild; };
const app = document.getElementById('app');
function add(h){ app.appendChild(el(h)); }

/* ---------- headline tiles ---------- */
const best = COND.reduce((a,c)=> D.summary[c].mean > D.summary[a].mean ? c : a, 'A');
const lift = (D.summary.C.mean - D.summary.A.mean);
const liftB = (D.summary.C.mean - D.summary.B.mean);
add(`<section class="sect">
  <div class="tiles">
    <div class="tile"><div class="k">Dojo vs no notes</div>
      <div class="v" style="color:${lift>0?'var(--series-3)':'var(--series-2)'}">${lift>0?'+':''}${lift.toFixed(1)}</div>
      <div class="n">mean score, held-out seeds</div></div>
    <div class="tile"><div class="k">Dojo vs self-notes</div>
      <div class="v" style="color:${liftB>0?'var(--series-3)':'var(--series-2)'}">${liftB>0?'+':''}${liftB.toFixed(1)}</div>
      <div class="n">same practice budget, no teacher</div></div>
    <div class="tile"><div class="k">Cost of the session</div>
      <div class="v">$${(D.spend.dojo_session_usd||0).toFixed(2)}</div>
      <div class="n">${esc(D.spend.mode)} · total ledger $${(D.spend.total_ledger_usd||0).toFixed(2)}</div></div>
    <div class="tile"><div class="k">Held-out episodes</div>
      <div class="v">${D.episodes.length}</div>
      <div class="n">${COND.length} conditions x ${D.eval_seeds.length} unseen seeds</div></div>
  </div>
</section>`);

/* ---------- bar chart: mean by condition ---------- */
(function(){
  const W=920,H=330,L=132,R=36,T=16,B=58;
  const means = COND.map(c=>D.summary[c].mean);
  const allPts = D.episodes.map(e=>e.score);
  const lo = Math.min(...means, ...allPts, 0), hi = 0;
  const pad = (hi-lo)*0.08 || 1;
  const y0 = lo-pad;
  const x = v => L + (v - y0)/(0 - y0) * (W-L-R);
  const rowH = (H-T-B)/COND.length;
  let ticks=[]; const step = Math.ceil(Math.abs(y0)/5/5)*5 || 5;
  for(let v=0; v>=y0; v-=step) ticks.push(v);

  let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Mean score by condition">`;
  ticks.forEach(t=>{ s+=`<line class="grid-line" x1="${x(t)}" y1="${T}" x2="${x(t)}" y2="${H-B}"${t===0?' stroke-width="1.5"':' opacity=".55"'}/>
    <text class="axis-text" x="${x(t)}" y="${H-B+18}" text-anchor="middle">${t}</text>`; });
  s += `<text class="axis-text" x="${(L+W-R)/2}" y="${H-B+40}" text-anchor="middle">mean episode score — 0 is perfect, less negative is better</text>`;

  COND.forEach((c,i)=>{
    const cy = T + rowH*i + rowH/2;
    const m = D.summary[c].mean, bh = 26;
    const xEnd = x(m), xZero = x(0);
    s += `<text class="cond-label" x="${L-14}" y="${cy-2}" text-anchor="end">${esc(D.conditions[c].label)}</text>`;
    s += `<text class="cond-sub" x="${L-14}" y="${cy+14}" text-anchor="end">${c}${c===best?' · best':''}</text>`;
    // bar grows leftward from zero; 4px rounded data-end away from baseline
    s += `<path d="M ${xZero} ${cy-bh/2} H ${xEnd+4} a4 4 0 0 0 -4 4 V ${cy+bh/2-4} a4 4 0 0 0 4 4 H ${xZero} Z"
            fill="${HUE[c]}"/>`;
    // per-seed dots, 2px surface ring so overlaps stay countable
    D.episodes.filter(e=>e.condition===c).forEach(e=>{
      s += `<circle cx="${x(e.score)}" cy="${cy}" r="4.5" fill="var(--surface-1)" stroke="${HUE[c]}" stroke-width="2"><title>seed ${e.seed}: ${e.score.toFixed(1)}</title></circle>`;
    });
    s += `<text class="bar-label" x="${xEnd-10}" y="${cy+5}" text-anchor="end">${m.toFixed(1)}</text>`;
  });
  s += `</svg>`;

  add(`<section class="sect">
    <h2>Held-out performance</h2>
    <p class="sect-note">Mean score across ${D.eval_seeds.length} unseen Meander seeds
      (${D.eval_seeds.join(', ')}), never used in practice. Hollow dots are the
      individual episodes behind each mean.</p>
    <div class="card">${s}</div>
  </section>`);
})();

/* ---------- table view (required relief for the contrast WARN) ---------- */
(function(){
  let rows = COND.map(c=>{
    const s=D.summary[c];
    return `<tr><td><span class="swatch" style="display:inline-block;background:${HUE[c]}"></span>
      ${esc(D.conditions[c].label)}</td>
      <td>${s.mean.toFixed(2)}</td><td>${s.std.toFixed(2)}</td>
      ${s.scores.map(v=>`<td>${v.toFixed(1)}</td>`).join('')}</tr>`;
  }).join('');
  add(`<section class="sect">
    <h2>The same numbers</h2>
    <div class="card scroll"><table>
      <thead><tr><th>Condition</th><th>Mean</th><th>Std</th>
        ${D.eval_seeds.map(s=>`<th>seed ${s}</th>`).join('')}</tr></thead>
      <tbody>${rows}</tbody></table>
      <p class="caveat">${esc(D.caveat)} ${esc(D.benchmark)}.
        Student <code>${esc(D.models.student)}</code>, teacher
        <code>${esc(D.models.teacher)}</code> on ${esc(D.models.provider)}.</p>
    </div></section>`);
})();

/* ---------- practice curve ---------- */
(function(){
  const cur = D.practice_curves || {};
  const series = [['C',cur.C||[]],['B',cur.B||[]]].filter(([,v])=>v.length);
  if(!series.length) return;
  const W=920,H=340,L=56,R=100,T=20,B=76;
  const n = Math.max(...series.map(([,v])=>v.length));
  const vals = series.flatMap(([,v])=>v.map(p=>p.score));
  const lo = Math.min(...vals,0), pad=(0-lo)*0.1||1, y0=lo-pad;
  const x = i => L + (n<2?0.5:i/(n-1)) * (W-L-R);
  const y = v => (H-B) - (v-y0)/(0-y0) * (H-B-T);

  let s=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Score per practice episode">`;
  const step = Math.ceil(Math.abs(y0)/5/5)*5 || 5;
  for(let v=0; v>=y0; v-=step){
    s+=`<line class="grid-line" x1="${L}" y1="${y(v)}" x2="${W-R}" y2="${y(v)}"${v===0?' stroke-width="1.5"':' opacity=".55"'}/>
        <text class="axis-text" x="${L-10}" y="${y(v)+4}" text-anchor="end">${v}</text>`;
  }
  for(let i=0;i<n;i++) s+=`<text class="axis-text" x="${x(i)}" y="${H-B+20}" text-anchor="middle">${i+1}</text>`;
  s+=`<text class="axis-text" x="${(L+W-R)/2}" y="${H-B+42}" text-anchor="middle">practice episode</text>`;

  series.forEach(([c,pts])=>{
    const d = pts.map((p,i)=>`${i?'L':'M'} ${x(i)} ${y(p.score)}`).join(' ');
    s+=`<path d="${d}" fill="none" stroke="${HUE[c]}" stroke-width="2" stroke-linejoin="round"/>`;
    pts.forEach((p,i)=>{
      s+=`<circle cx="${x(i)}" cy="${y(p.score)}" r="5" fill="${HUE[c]}" stroke="var(--surface-1)" stroke-width="2"><title>${D.conditions[c].label} · ep ${i+1} (seed ${p.seed}): ${p.score.toFixed(1)}${p.scaffold_level!=null?` · scaffold ${p.scaffold_level}`:''}</title></circle>`;
      if(p.scaffold_level!=null)
        s+=`<text class="axis-text" x="${x(i)}" y="${y(p.score)-13}" text-anchor="middle" font-weight="640" fill="${HUE[c]}">L${p.scaffold_level}</text>`;
    });
    const last=pts[pts.length-1];
    s+=`<text class="cond-label" x="${x(pts.length-1)+12}" y="${y(last.score)+4}" fill="${HUE[c]}">${esc(D.conditions[c].label)}</text>`;
  });
  s+=`</svg>`;

  add(`<section class="sect">
    <h2>The practice curve</h2>
    <p class="sect-note"><strong>L3</strong> the teacher names the next action each step ·
      <strong>L2</strong> it says only what to look at · <strong>L1</strong> mistakes are flagged
      after the episode · <strong>L0</strong> solo test. Help fades after a good episode and
      comes back after a bad one — so the level is itself a readout of how the student is doing.</p>
    <div class="card">
      <ul class="legend">${series.map(([c])=>`<li><span class="swatch" style="background:${HUE[c]}"></span>${esc(D.conditions[c].label)}</li>`).join('')}</ul>
      ${s}
    </div></section>`);
})();

/* ---------- lessons ---------- */
(function(){
  const L = D.lessons||{};
  const col = (c,title)=>`<div class="card"><h2 style="margin-bottom:12px">
      <span class="swatch" style="display:inline-block;background:${HUE[c]}"></span> ${title}</h2>
      <ol class="lessons">${(L[c]||[]).map(x=>`<li>${esc(x)}</li>`).join('') || '<li class="hint">none</li>'}</ol></div>`;
  add(`<section class="sect">
    <h2>What the agent wrote down</h2>
    <p class="sect-note">These notes are the entire mechanism. Same model, same weights —
      the only thing that differs between conditions is the text above the observation.</p>
    <div class="two">${col('C','Dojo lesson pack')}${col('B','Self-written notes')}</div>
  </section>`);
})();

/* ---------- replay ---------- */
(function(){
  const r = D.replay; if(!r || !r.trajectory) return;
  const rows = r.trajectory.map(t=>{
    const cls = t.reward < -1 ? 'bad' : (t.reward===0 ? '' : 'good');
    return `<tr class="${cls}">
      <td>${t.step}</td><td>${esc(t.action)}</td>
      <td>${t.reward.toFixed(1)}</td><td>${t.cumulative.toFixed(1)}</td>
      <td class="hint">${esc(t.hint||'—')}</td>
      <td>${esc(t.reason||'')}</td></tr>`;
  }).join('');
  add(`<section class="sect">
    <h2>Replay — one paid practice episode</h2>
    <p class="sect-note">Session <code>${esc(r.session_id)}</code>, seed ${r.seed},
      scaffold level ${r.scaffold_level}, final score ${r.score.toFixed(1)}.
      The teacher's line is what the agent paid for.</p>
    <div class="card scroll"><table class="replay">
      <thead><tr><th>#</th><th>Action</th><th>r</th><th>cum</th>
        <th>Teacher hint</th><th>Agent's reason</th></tr></thead>
      <tbody>${rows}</tbody></table></div>
  </section>`);
})();

/* ---------- spend ---------- */
(function(){
  const e = D.spend.entries||[];
  add(`<section class="sect">
    <h2>Spend</h2>
    <p class="sect-note">One paid call opens a session; hints and critiques are free
      inside it. <span class="pill">${esc(D.spend.mode)} mode</span></p>
    <div class="card scroll"><table>
      <thead><tr><th>Route</th><th>Mode</th><th>USD</th></tr></thead>
      <tbody>${e.map(x=>`<tr><td>${esc(x.route)}</td><td>${esc(x.mode)}</td><td>$${x.amount_usd.toFixed(2)}</td></tr>`).join('')}
      <tr><td><strong>Total</strong></td><td></td><td><strong>$${(D.spend.total_ledger_usd||0).toFixed(2)}</strong></td></tr>
      </tbody></table></div>
  </section>`);
})();

document.getElementById('foot').innerHTML =
  `${esc(D.benchmark)} · practice seeds ${D.practice_seeds.join(', ')} ·
   held-out seeds ${D.eval_seeds.join(', ')} · generated
   ${new Date(D.generated*1000).toISOString().slice(0,16).replace('T',' ')} UTC ·
   eval wall-clock ${D.elapsed_s}s`;
</script>
</body>
</html>
"""


def main():
    with open(RESULTS) as f:
        data = json.load(f)
    # Inline safely: </script> inside JSON would close the tag early.
    blob = json.dumps(data).replace("</", "<\\/")
    with open(OUT, "w") as f:
        f.write(PAGE.replace("__DATA__", blob))
    print(f"wrote {OUT} ({os.path.getsize(OUT)/1024:.0f} KB)")


if __name__ == "__main__":
    main()
