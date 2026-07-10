// ---------- tabs ----------
document.querySelectorAll(".tabs button").forEach(b=>b.onclick=()=>{
  document.querySelectorAll(".tabs button").forEach(x=>x.classList.toggle("on",x===b));
  document.querySelectorAll(".view").forEach(v=>v.classList.toggle("on", v.id==="v-"+b.dataset.t));
});

// ---------- eval (live /api/matchrate) ----------
const $=s=>document.querySelector(s);
let scope="all",mode="raw";
async function render(){
  const apiMode='exact';
  let d;
  try{d=await(await fetch(`/api/matchrate?dataset=${encodeURIComponent(scope)}&mode=${apiMode}`,{cache:'no-store'})).json();}
  catch(e){d={n:0,rank1:0,top3:0,top5:0,miss:0,counts:{},by_provider:{},matching_policy:{}};}
  const n=d.n||0, pct=x=>n?Math.round(100*x/n):0;
  const excl=[]; if(d.excluded_korea_pending_kakao)excl.push(`KR 제외 ${d.excluded_korea_pending_kakao}`); if(d.excluded_non_poi)excl.push(`non_poi ${d.excluded_non_poi}`); if(d.excluded_no_gt)excl.push(`no_gt ${d.excluded_no_gt}`); if(d.no_provider_data)excl.push(`provider_data 없음 ${d.no_provider_data}`);
  $("#meta").innerHTML=`후보검색 평가 가능 GT <b>n=${n}</b> · 제외/대기: ${excl.join(' · ')||'-'} · 매칭: <b>동일 provider canonical name == candidate name</b> · 후보공급원: 현재 KR 제외 / non-KR=MapKit`;
  const set=(id,c)=>{$("#p-"+id).textContent=pct(c)+"%";$("#c-"+id).textContent=c+" / "+n;};
  set("r1",d.rank1||0);set("t3",d.top3||0);set("t5",d.top5||0);set("miss",d.miss||0);
  $("#flip").classList.add("hidden");
  // Only the N the API actually measures: rank-1 (=top-1), top-3, top-5. No interpolation.
  drawCurve([[1,pct(d.rank1||0)],[3,pct(d.top3||0)],[5,pct(d.top5||0)]]);
}
function drawCurve(points){
  const W=580,H=260,pl=44,pr=16,pt=16,pb=32,xs=[1,3,5];
  const x=i=>pl+(W-pl-pr)*(i/(xs.length-1)),y=v=>pt+(H-pt-pb)*(1-v/100);
  let g="";
  for(let v=0;v<=100;v+=25)g+=`<line x1="${pl}" y1="${y(v)}" x2="${W-pr}" y2="${y(v)}" stroke="rgba(255,255,255,.07)"/><text x="${pl-8}" y="${y(v)+4}" text-anchor="end" fill="var(--ink3)" font-size="11" font-family="var(--mono)">${v}%</text>`;
  xs.forEach((n,i)=>g+=`<text x="${x(i)}" y="${H-11}" text-anchor="middle" fill="var(--ink3)" font-size="11" font-family="var(--mono)">${n}</text>`);
  const vals=points.map(p=>p[1]);
  const poly=`<polyline points="${vals.map((v,i)=>`${x(i)},${y(v)}`).join(" ")}" fill="none" stroke="var(--green)" stroke-width="2.4"/>`;
  const dots=vals.map((v,i)=>`<circle cx="${x(i)}" cy="${y(v)}" r="3.5" fill="var(--green)"/>`).join("");
  const labs=vals.map((v,i)=>`<text x="${x(i)}" y="${y(v)-9}" text-anchor="middle" fill="var(--ink)" font-size="10.5" font-family="var(--mono)">${v}%</text>`).join("");
  $("#curve").innerHTML=g+poly+dots+labs;
}
function drawBars(algos){
  const W=580,H=250,pl=44,pr=16,pt=16,pb=42;
  if(!algos.length){
    $("#bars").innerHTML=`<text x="${W/2}" y="${H/2-8}" text-anchor="middle" fill="var(--ink2)" font-size="13" font-family="var(--mono)">제출된 알고리즘 없음 — ② 평가 실행에서 predict() 제출</text><text x="${W/2}" y="${H/2+16}" text-anchor="middle" fill="var(--ink3)" font-size="11.5">MapKit/Kakao는 후보 공급원이며 식별 정확도 막대가 아니다</text>`;
    return;
  }
  const y=v=>pt+(H-pt-pb)*(1-v/100), step=(W-pl-pr)/algos.length, bw=Math.min(70,step*0.5);
  let g="";
  for(let v=0;v<=100;v+=25)g+=`<line x1="${pl}" y1="${y(v)}" x2="${W-pr}" y2="${y(v)}" stroke="rgba(255,255,255,.07)"/><text x="${pl-8}" y="${y(v)+4}" text-anchor="end" fill="var(--ink3)" font-size="11" font-family="var(--mono)">${v}%</text>`;
  const cols=["var(--green)","var(--cyan)","var(--violet)","var(--gold)","var(--orange)"];
  algos.forEach(([name,acc],i)=>{
    const cx=pl+step*(i+0.5);
    g+=`<rect x="${cx-bw/2}" y="${y(acc)}" width="${bw}" height="${y(0)-y(acc)}" rx="5" fill="${cols[i%cols.length]}"/>`;
    g+=`<text x="${cx}" y="${y(acc)-7}" text-anchor="middle" fill="var(--ink)" font-size="12.5" font-weight="700" font-family="var(--mono)">${acc}%</text>`;
    g+=`<text x="${cx}" y="${H-22}" text-anchor="middle" fill="var(--ink2)" font-size="11.5">${name}</text>`;
  });
  $("#bars").innerHTML=g;
}
// ---------- case analysis (real /api/records) ----------
const esc=s=>String(s==null?'':s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
let CASES=[],curOutcome='all',curCaseIdx=null;
const OC_LABEL={correct:'rank1',selection:'rank>1',retrieval:'검색실패',non_poi:'non_poi',deferred:'deferred',no_gt:'no_gt',other:'기타'};
const OC_ORDER=['all','correct','selection','retrieval','non_poi','deferred','no_gt'];
const providerExactEq=(a,b)=>{a=(a||'').trim();b=(b||'').trim();return !!(a&&b&&a===b);};
async function loadCases(){
  try{const r=await fetch('/api/records?dataset=linkedspaces',{cache:'no-store'});CASES=await r.json();}
  catch(e){CASES=[];}
  computeCoverage();renderChips();renderCaseList();renderParams();
}
// top-K별 GT 검색 커버리지 (실측: app_poi_rank ≤ K 비율). base = 베이스라인 있는 user GT 행.
function computeCoverage(){
  const base=CASES.filter(c=>c.outcome==='correct'||c.outcome==='selection'||c.outcome==='retrieval');
  window.COVERAGE={}; const n=base.length; if(!n)return;
  const within=k=>base.filter(c=>{if(!c.rank||c.rank==='MISS')return false;return k==='전체'?true:parseInt(c.rank)<=k;}).length;
  [3,5,10,'전체'].forEach(k=>window.COVERAGE[k]=Math.round(100*within(k)/n));
  window.COVERAGE.__n=n;
}
const outCount=o=>o==='all'?CASES.length:CASES.filter(c=>c.outcome===o).length;
function renderChips(){
  $("#chips").innerHTML=OC_ORDER.filter(o=>o==='all'||outCount(o)).map(o=>
    `<span class="chip ${o===curOutcome?'on':''}" data-o="${o}">${o==='all'?'전체':OC_LABEL[o]}<span class="c">${outCount(o)}</span></span>`).join('');
  $("#chips").querySelectorAll('.chip').forEach(el=>el.onclick=()=>{curOutcome=el.dataset.o;renderChips();renderCaseList();});
}
function renderCaseList(){
  const list=CASES.map((c,i)=>[c,i]).filter(([c])=>curOutcome==='all'||c.outcome===curOutcome);
  $("#caselist").innerHTML=list.slice(0,200).map(([c,i])=>
    `<div class="ci ${i===curCaseIdx?'sel':''}" data-i="${i}"><img loading="lazy" src="${c.photo_url}" onerror="this.style.visibility='hidden'"><span class="g">${esc(c.gt||'(GT 없음)')}</span><span class="oc ${c.outcome}">${OC_LABEL[c.outcome]||c.outcome}</span></div>`).join('')
    || '<div style="color:var(--ink3);font-size:12px;padding:10px">해당 케이스 없음</div>';
  $("#caselist").querySelectorAll('.ci').forEach(el=>el.onclick=()=>showCase(+el.dataset.i));
}
function showCase(i){
  curCaseIdx=i;const c=CASES[i];
  const E={
    correct:['rgba(95,211,123,.1)','MapKit 1위 후보가 GT와 exact match.'],
    selection:['rgba(255,159,69,.1)',`GT는 후보 <b>rank ${esc(c.rank)}</b> — MapKit 1위는 '<b>${esc(c.baseline_pick)}</b>'이다. <b>GT가 후보에는 있으므로 selection 알고리즘이 고를 여지는 있음.</b>`],
    retrieval:['rgba(255,107,92,.1)',`GT가 250m 후보(${esc(c.n_wide)}개)에 <b>없음</b>. 알고리즘으론 못 고침 — 반경·API·no_venue 문제. <i>동일 provider exact name 기준으로 확인한다.</i>`],
    non_poi:['rgba(118,131,184,.1)','POI 아님. 정답은 거절.'],
    deferred:['rgba(118,131,184,.1)','베이스라인 미실행(한국 등).'],
    no_gt:['rgba(118,131,184,.1)','GT 라벨 없음.'],
  }[c.outcome]||['rgba(118,131,184,.1)',''];
  const gtIn=(c.candidates||[]).some(cd=>providerExactEq(cd.name,c.gt));
  const cands=(c.candidates||[]).map(cd=>{
    const isgt=providerExactEq(cd.name,c.gt),ispick=providerExactEq(cd.name,c.baseline_pick);
    const tags=(isgt?'<span class="tg" style="background:rgba(95,211,123,.2);color:var(--green)">GT</span>':'')+(ispick?'<span class="tg" style="background:rgba(255,159,69,.2);color:var(--orange)">MapKit 1위</span>':'');
    return `<div class="cand ${isgt?'isgt':''} ${ispick?'ispick':''}"><span>${esc(cd.name)}</span><span><span style="color:var(--ink3);font-family:var(--mono);font-size:11px">${esc(cd.dist)}</span>${tags}</span></div>`;
  }).join('');
  $("#casedetail").innerHTML=`
    ${c.photo_url?`<img src="${c.photo_url}" onerror="this.style.display='none'">`:''}
    <div class="drow"><span class="lab">GT</span><span class="val gt">${esc(c.gt||'(없음)')}</span></div>
    <div class="drow"><span class="lab">MapKit 1위</span><span class="val">${esc(c.baseline_pick||'—')} <span style="color:var(--ink3)">(최근접 · rank ${esc(c.rank)})</span></span></div>
    <div class="expl" style="background:${E[0]}"><b>${OC_LABEL[c.outcome]}</b> — ${E[1]}</div>
    <div class="drow"><span class="lab">후보 top3</span><span class="val" style="flex:1">${cands||'<span style="color:var(--ink3)">없음</span>'}${(c.rank&&c.rank!=='MISS'&&!gtIn)?`<div style="color:var(--ink3);font-size:11px;margin-top:2px">※ GT는 rank ${esc(c.rank)} — 상위 3 밖 (전체 ${esc(c.n_wide)}개 중)</div>`:''}</span></div>
    <div class="drow"><span class="lab">OCR</span><span class="val" style="font-size:12px;color:${c.ocr_text?'var(--ink2)':'var(--ink3)'}">${esc(c.ocr_text||'(텍스트 없음)')}</span></div>
    <div class="drow"><span class="lab">좌표</span><span class="val" style="font-family:var(--mono);font-size:12px">${esc(c.lat)}, ${esc(c.lon)}</span></div>
    <div class="drow"><span class="lab">카테고리</span><span class="val">${esc(c.category)}</span></div>`;
  renderCaseList();
}
$("#scope").onchange=e=>{scope=e.target.value;render();};

render();
loadCases();

// ---------- overview: row structure (라벨 컬럼 · 채움 · 입력벡터) — live /api/overview fill ----------

async function loadOverviewSummary(){
  const by=id=>document.getElementById(id);
  try{
    const d=await(await fetch('/api/overview',{cache:'no-store'})).json();
    const total=d.total||0;
    const pct=c=>total?Math.round(100*c/total):0;
    const color=v=>String(v||'var(--blue)').startsWith('var(')?v:`var(--${v})`;
    by('k-total').textContent=total;
    by('k-gt').textContent=d.gt_present||0;
    by('k-photo').textContent=d.photo_present||0;
    by('k-country').textContent=(d.countries||[]).length;
    by('sourcebars').innerHTML=(d.sources||[]).map(x=>`<div class="src"><span class="dot" style="background:${color(x.color)}"></span><span>${esc(x.key)} <span class="prov">· ${esc(x.owner||'')} · ${esc(x.source_type||x.desc||'')}</span></span><b>${x.count}</b></div>`).join('');
    by('confidencebars').innerHTML=(d.confidence||[]).map(x=>`<div class="bar"><span class="lbl">${esc(x.key)}</span><div class="track"><div class="fill" style="width:${pct(x.count)}%;background:${color(x.color)}"></div></div><span class="v">${x.count}</span></div>`).join('');
    by('countrybars').innerHTML=(d.countries||[]).map((x,i)=>`<div class="bar"><span class="lbl">${esc(x.flag||'·')} ${esc(x.key)}</span><div class="track"><div class="fill" style="width:${pct(x.count)}%;background:${['var(--blue)','var(--pink)','var(--cyan)','var(--violet)','var(--orange)'][i%5]}"></div></div><span class="v">${x.count}</span></div>`).join('');
    by('pipelinebars').innerHTML=(d.pipeline||[]).map(x=>{const p=total?Math.round(100*(x.merged||x.extracted||0)/total):0;const st=x.status==='done'?'완료':(x.status==='run'?'진행중':'대기');const col=x.status==='done'?'var(--green)':(x.status==='run'?'var(--orange)':'#333c66');return `<div class="pl"><span class="lbl">${esc(x.label)}</span><div class="track"><div class="seg" style="width:${p}%;background:${col}"></div></div><span class="st ${x.status}">${st}</span></div>`}).join('');
  }catch(e){ console.warn('overview load failed',e); }
}
// Row structure is rendered live from /api/overview `schema` (config-driven).
// No hardcoded column list — schema_groups / CSV changes reflect on reload.
// The 출처(dataset) dropdown recomputes 채움% from per-dataset fills.
let _rowstruct=null;
async function loadRowStruct(){
  try{_rowstruct=await(await fetch('/api/overview',{cache:'no-store'})).json();}catch(e){_rowstruct={};}
  const sel=$("#rowstruct-src");
  if(sel && !sel.dataset.init){
    const dss=_rowstruct.datasets||[];
    sel.innerHTML='<option value="__all">전체</option>'+dss.map(x=>`<option value="${esc(x)}">${esc(x)}</option>`).join('');
    sel.dataset.init='1';
    sel.addEventListener('change',renderRowStruct);
  }
  renderRowStruct();
}
function renderRowStruct(){
  const d=_rowstruct||{},schema=d.schema||[];
  const sel=$("#rowstruct-src"),src=sel?sel.value:'__all',isAll=src==='__all';
  const total=isAll?Number(d.total||0):Number((d.total_by_dataset||{})[src]||0);
  const fbd=isAll?null:((d.fill_by_dataset||{})[src]||{});
  const RC={in:'var(--blue)',gt:'var(--gold)',bl:'var(--green)',mt:'var(--ink3)'};
  $("#rowstruct").innerHTML=schema.map(s=>{
    const rep=(s.cols&&s.cols[0])||'';
    const f=isAll?Number(s.fill||0):Number(fbd[rep]||0);
    const pct=total?Math.round(100*f/total):0;
    const color=pct>=90?'var(--green)':(pct===0?'var(--ink3)':'var(--orange)');
    const rcolor=RC[s.role_key]||'var(--ink3)';
    return `<tr><td class="nm3">${esc(s.group)}</td>
      <td class="rl" style="color:${rcolor}">${esc(s.role_label||s.role_key||'')}</td>
      <td><div class="fb2"><div class="mt2"><div class="mf2" style="width:${pct}%;background:${color}"></div></div><span class="mp2">${pct}%</span></div></td>
      <td class="m3">${s.desc||''}</td></tr>`;
  }).join('');
}
loadOverviewSummary();
loadRowStruct();

// ---------- run workspace (submission harness pending; no generated runs) ----------
const REG={};
let runsList=[];
const g=id=>document.getElementById(id);
// 입력 파라미터 = 신호 + 추출 방법(provenance). methods[0]=현재, 그 외=대안(이후).
const PARAMS=[
  {k:"image", name:"이미지", methods:["원본 사진 (jpg)"], on:false},
  {k:"lat,lon", name:"좌표", methods:["EXIF GPS"], on:true},
  {k:"timestamp", name:"촬영 시각", methods:["EXIF DateTimeOriginal"], on:false},
  {k:"ocr_text", name:"OCR 텍스트", methods:["Vision VNRecognizeTextRequest","Tesseract (이후)","Google Vision (이후)"], on:true},
  {k:"vlm_caption", name:"VLM 설명", methods:["FastVLM-0.5B","LLaVA (이후)"], on:false},
  {k:"nearby_candidates", name:"주변 후보", methods:["MapKit MKLocalPointsOfInterest","Google Places (이후)","Kakao Local (이후)"], on:true, topk:[3,5,10,"전체"]},
  {k:"city,country,address", name:"역지오코딩", methods:["Apple CLGeocoder","Google Geocoding (이후)"], on:false},
  {k:"category", name:"카테고리", methods:["GT 라벨"], on:false, warn:"⚠ GT유래·실사용불가"},
];
function methodOf(i){const s=document.querySelector(`.prow[data-pi="${i}"] select[data-mi]`);return s?s.value:PARAMS[i].methods[0];}
function renderParams(){
  g('params').innerHTML='<div class="plist">'+PARAMS.map((p,i)=>{
    const method=p.methods.length>1
      ? `<select data-mi="${i}">${p.methods.map((m,j)=>`<option${j===0?' selected':''}>${m}</option>`).join('')}</select>`
      : `<span class="m">${p.methods[0]}</span>`;
    const topk=p.topk?`<select class="topk" data-ti="${i}" title="후보 상위 몇 개를 함수에 넘길지 · 괄호는 그 안에 든 GT 비율(MapKit 실측 검색 상한)">${p.topk.map(nn=>{const cv=(window.COVERAGE&&window.COVERAGE[nn]!=null)?` · GT ${window.COVERAGE[nn]}%`:'';return `<option value="top ${nn}"${nn===5?' selected':''}>top ${nn}${cv}</option>`;}).join('')}</select>`:'';
    return `<label class="prow" data-pi="${i}"><input type="checkbox" data-k="${p.k}"${p.on?' checked':''}>
      <span class="nm">${p.name}${p.warn?` <span class="warn2">${p.warn}</span>`:''}</span>
      <span class="pk">${p.k}</span><span class="mcell">${method}${topk}</span></label>`;
  }).join('')+'</div>';
  g('params').querySelectorAll('input,select').forEach(el=>el.onchange=updSig);
  updSig();
}
const ACC={
  'image':['img','case["photo_path"]'],
  'lat,lon':['lat, lon','case["lat"], case["lon"]'],
  'timestamp':['ts','case["timestamp"]'],
  'ocr_text':['ocr','case["ocr_text"]'],
  'vlm_caption':['vlm','case["vlm_caption"]'],
  'nearby_candidates':['cands','case["nearby_candidates"]'],
  'city,country,address':['geo','case["geocode"]'],
  'category':['cat','case["category_hint"]'],
};
function updSig(){
  const rows=[...document.querySelectorAll('.prow')].filter(r=>r.querySelector('input').checked);
  const cfg=[],lines=[];
  rows.forEach(r=>{
    const i=+r.dataset.pi,p=PARAMS[i],tk=r.querySelector('.topk');
    const a=ACC[p.k]||[p.k.split(',')[0],`case["${p.k}"]`];
    lines.push(`    ${a[0]} = ${a[1]}`.padEnd(40)+`# ${p.name}`);
    const method=methodOf(i)+(tk?` · ${tk.value}`:'');
    cfg.push(`#   ${(p.k+':').padEnd(22)}${method}`);
  });
  const header=cfg.length?`# ── run config (드롭다운 선택 · 하네스가 이 설정으로 case 번들 생성) ──\n${cfg.join('\n')}\n`:'';
  g('loadsnippet').textContent=`${header}def predict(case):\n${lines.join('\n')||'    pass'}\n    # TODO: 예측 로직\n    return { "prediction": ..., "reason": ... }`;
}
function updVer(){
  const nm=g('tname').value.trim(), ex=REG[nm];
  g('verstat').innerHTML = (ex&&ex.length)
    ? `기존 존재: v${ex.join(' · v')} → 자동 저장 시 <span class="bg">v${Math.max(...ex)+1}</span> · 또는 저장 모드에서 특정 버전 덮어쓰기`
    : `새 테스트 → <span class="bg">v1</span>`;
}
function renderRuns(){
  g('runsbody').innerHTML=runsList.length ? runsList.map(r=>
    `<tr><td class="name">${r.name}</td><td><code>v${r.v}</code></td><td><code>${r.script||'—'}</code></td><td><code>${r.inp}</code></td><td>${r.scope}</td><td>${r.r1}</td><td><span class="stt ${r.st}">${r.st}</span></td></tr>`).join('') : '<tr><td colspan="7" style="color:var(--ink3);font-size:12px">아직 제출된 알고리즘 실행 결과가 없습니다. 후보검색 평가는 ③ 탭의 실제 GT/MapKit rank만 표시합니다.</td></tr>';
}
let scriptName='',scriptText='',scriptLang='python';
const LANG_BY_EXT={py:'python',c:'c',cpp:'cpp',rs:'rust',js:'node',sh:'sh'};
g('scriptfile').onchange=e=>{
  const f=e.target.files[0]; scriptName=f?f.name:''; scriptText='';
  g('filelabel').textContent=f?`📎 ${f.name} 첨부됨`:'📎 predict 계약을 구현한 스크립트를 첨부 — 클릭 또는 드롭';
  document.querySelector('.filedrop').classList.toggle('has',!!f);
  if(f){
    scriptLang=LANG_BY_EXT[(f.name.split('.').pop()||'').toLowerCase()]||'python';
    const rd=new FileReader(); rd.onload=()=>{scriptText=rd.result||'';}; rd.readAsText(f);
  }
};
const uploadZip=g('uploadZip');
if(uploadZip){
  uploadZip.onchange=async e=>{
    const f=e.target.files[0];
    const status=g('uploadStatus');
    if(!f) return;
    status.textContent=`검증 중: ${f.name}`;
    try{
      const res=await fetch('/api/validate-upload-package',{method:'POST',body:f,headers:{'Content-Type':'application/zip'}});
      const data=await res.json();
      const errs=(data.errors||[]).slice(0,5).map(x=>`${x.code||'error'}${x.row?` row ${x.row}`:''}: ${x.message}`).join(' / ');
      status.textContent=data.ok
        ? `검증 성공: ${data.row_count||0}개 행, ${data.image_count||0}개 사진. 다음 단계에서 EXIF·지역·provider를 자동 추출한다.`
        : `검증 실패: ${errs||data.error||'업로드 패키지를 확인하세요.'}`;
    }catch(err){ status.textContent=`검증 요청 실패: ${err.message}`; }
  };
}
g('tname').oninput=updVer;
// selected input-parameter keys (checked rows) → sent to the run harness
function selectedParams(){
  return [...document.querySelectorAll('.prow')]
    .filter(r=>r.querySelector('input').checked)
    .map(r=>PARAMS[+r.dataset.pi].k);
}
g('runbtn').onclick=async()=>{
  if(!scriptText){ g('runhint').textContent='먼저 predict() 스크립트를 첨부하세요.'; return; }
  const name=(g('tname').value||'').trim()||'algorithm';
  const scope=g('rscope').value, save=g('savemode').value;
  const body={name,scope,mode:'exact',save_mode:save,lang:scriptLang,params:selectedParams(),script_text:scriptText};
  g('runbtn').disabled=true; g('runhint').textContent=`실행 중: ${name} (${scope}) …`;
  try{
    const res=await fetch('/api/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const data=await res.json();
    if(data.ok){
      const m=data.metrics||{};
      g('runhint').textContent=`완료: ${data.name} v${data.version} · 식별 정확도 ${m.accuracy_pct}% (${m.correct}/${m.n_eligible}, 무응답 ${m.abstained}, 오류 ${m.errored})`;
      await loadRuns();
    }else{
      g('runhint').textContent=`실패: ${data.error||'실행 오류'}`;
    }
  }catch(err){ g('runhint').textContent=`요청 실패: ${err.message}`; }
  finally{ g('runbtn').disabled=false; }
};
// live runs from /api/runs → 최근 실행 표 + 식별 정확도 막대(알고리즘별, 이름당 최신 버전)
async function loadRuns(){
  let runs=[];
  try{ runs=(await (await fetch('/api/runs',{cache:'no-store'})).json()).runs||[]; }catch(e){}
  Object.keys(REG).forEach(k=>delete REG[k]);
  runs.forEach(r=>{ (REG[r.name]=REG[r.name]||[]).push(r.version); });
  Object.values(REG).forEach(a=>a.sort((x,y)=>x-y));
  runsList=runs.map(r=>({name:r.name,v:r.version,script:r.lang,inp:(r.params||[]).length+'개',scope:r.scope,r1:r.accuracy_pct+'%',st:'ok'}));
  renderRuns();updVer();
  // one bar per algorithm name, latest version wins
  const latest={};
  runs.forEach(r=>{ if(!latest[r.name]||r.version>latest[r.name].version) latest[r.name]=r; });
  drawBars(Object.values(latest).sort((a,b)=>b.accuracy_pct-a.accuracy_pct).map(r=>[`${r.name} v${r.version}`,r.accuracy_pct]));
}
renderParams();updVer();loadRuns();

// ================= ④ dataset management + jobs + ① live progress =================
const gid=id=>document.getElementById(id);
let _dsData=null, _jobTimer=null, _watchJob=null, _pollBusy=false;
// step -> ① 신호 파이프라인 row label to annotate while running
const STEP_PIPELINE={ocr:'Vision OCR', mapkit_nearby:'MapKit 베이스라인', gt_mapkit:'MapKit 정규명(GT)'};

async function loadDatasets(){
  let d; try{ d=await(await fetch('/api/datasets',{cache:'no-store'})).json(); }catch(e){ return; }
  _dsData=d;
  const sig=d.signals_meta||{};
  gid('dsTable').innerHTML=(d.datasets||[]).map(ds=>{
    const bars=Object.values(ds.signals||{}).map(s=>{
      const dis=s.status&&s.status!=='ok';
      const col=dis?'#333c66':(s.pct>=90?'var(--green)':(s.pct===0?'var(--ink3)':'var(--orange)'));
      return `<div class="fb2" title="${esc(s.label)} ${s.fill}/${ds.count}${dis?' · '+esc(s.status):''}"><span class="mp2" style="width:96px;text-align:left;color:var(--ink3)">${esc(s.label)}</span><div class="mt2"><div class="mf2" style="width:${s.pct}%;background:${col}"></div></div><span class="mp2">${dis?'—':s.pct+'%'}</span></div>`;
    }).join('');
    return `<tr><td class="nm3">${esc(ds.key)}${ds.known?'':' <span style="color:var(--orange)" title="config sources 없음">⚠</span>'}<div style="color:var(--ink3);font-size:11px">${esc(ds.label||'')}</div></td><td class="m3">${ds.count}</td><td><div style="display:flex;flex-direction:column;gap:4px">${bars}</div></td><td><button class="btn" data-del="${esc(ds.key)}" style="border-color:rgba(255,107,92,.45);background:rgba(255,107,92,.10);color:#ffb3aa">삭제</button></td></tr>`;
  }).join('')||'<tr><td colspan="4" style="color:var(--ink3)">데이터셋 없음</td></tr>';
  gid('rerunDataset').innerHTML=(d.datasets||[]).map(ds=>`<option value="${esc(ds.key)}">${esc(ds.key)}</option>`).join('');
  gid('rerunStep').innerHTML=Object.entries(sig).map(([name,s])=>{
    const dis=s.status&&s.status!=='ok';
    return `<option value="${esc(s.step||name)}"${dis?' disabled':''}>${esc(s.label)}${dis?' · '+esc(s.status):''}</option>`;
  }).join('');
  gid('dsTable').querySelectorAll('button[data-del]').forEach(b=>b.onclick=()=>deleteDataset(b.dataset.del));
}

async function deleteDataset(key){
  const ds=(_dsData&&_dsData.datasets||[]).find(x=>x.key===key)||{count:'?'};
  if(!confirm(`데이터셋 "${key}" (${ds.count}행) 삭제?\n\nCSV에서 행 제거(백업 자동 생성). 마지막 1개면 거부.\n사진 파일·config 항목은 그대로 유지됩니다.`)) return;
  try{
    const res=await fetch(`/api/jobs?step=delete_dataset&dataset=${encodeURIComponent(key)}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({delete_photos:false,remove_config_source:false})});
    const d=await res.json();
    if(!d.ok){ alert('삭제 실패: '+(res.status===409?'다른 작업 실행중':(d.error||res.status))); return; }
    watchJob(d.job_id);
  }catch(e){ alert('삭제 요청 실패: '+e.message); }
}

async function doRerun(){
  const step=gid('rerunStep').value, dataset=gid('rerunDataset').value;
  const onlyEmpty=gid('rerunOnlyEmpty').checked?1:0, hint=gid('rerunHint'); hint.textContent='';
  if(!step){ hint.textContent='단계를 선택하세요'; return; }
  try{
    const res=await fetch(`/api/jobs?step=${encodeURIComponent(step)}&dataset=${encodeURIComponent(dataset)}&only_empty=${onlyEmpty}`,{method:'POST'});
    const d=await res.json();
    if(!d.ok){ hint.textContent=res.status===409?'다른 작업 실행중':(res.status===501?'미구현 단계':(d.error||'실패')); if(res.status===409) pollJobs(); return; }
    hint.textContent=`시작됨 (${d.job_id})`; watchJob(d.job_id);
  }catch(e){ hint.textContent='요청 실패: '+e.message; }
}

function watchJob(id){ _watchJob=id; startJobPolling(); }

function fmtResult(r){
  if(!r) return '';
  if(r.step==='delete_dataset') return `삭제 ${r.removed_rows}행 · backup`;
  const p=[]; if(r.filled!=null)p.push(`채움 ${r.filled}/${r.targets!=null?r.targets:'?'}`);
  if(r.counts)p.push(Object.entries(r.counts).map(([k,v])=>`${k}:${v}`).join(' '));
  return p.join(' · ')||(r.ok?'ok':'');
}

async function pollJobs(){
  let d; try{ d=await(await fetch('/api/jobs',{cache:'no-store'})).json(); }catch(e){ return null; }
  const active=(d.jobs||[]).find(j=>j.job_id===d.active);
  const ab=gid('jobActive');
  if(ab){ if(active){ const pr=active.progress; ab.innerHTML=`<span style="color:var(--orange)">● 실행중</span> ${esc(active.step)}${active.params&&active.params.dataset?' · '+esc(active.params.dataset):''} · ${active.elapsed_s||0}s${pr?` · ${pr.done}/${pr.total}`:''}`; } else ab.textContent='실행 중인 작업 없음.'; }
  const jl=gid('jobList');
  if(jl){
    const jobs=(d.jobs||[]).slice().sort((a,b)=>(b.started||0)-(a.started||0)).slice(0,8);
    jl.innerHTML=jobs.map(j=>{
      const sc=j.status==='done'?'stt ok':(j.status==='error'?'stt':'stt run2');
      const est=j.status==='error'?'background:rgba(255,107,92,.15);color:var(--red)':'';
      return `<tr><td class="name">${esc(j.step)}</td><td>${esc((j.params&&j.params.dataset)||'전체')}${j.params&&j.params.only_empty?' · 빈행':''}</td><td><span class="${sc}" style="${est}">${esc(j.status)}</span></td><td class="m3">${j.elapsed_s!=null?j.elapsed_s+'s':''}</td><td style="font-family:var(--mono);font-size:11px;color:var(--ink2)">${esc(fmtResult(j.result)||j.error||'')}</td></tr>`;
    }).join('');
  }
  if(_watchJob){ const wj=(d.jobs||[]).find(j=>j.job_id===_watchJob); const lg=gid('jobLog'); if(wj&&lg){ lg.style.display='block'; lg.textContent=(wj.log_tail||[]).join('\n'); } }
  return d;
}

async function pollTick(){
  if(_pollBusy) return; _pollBusy=true;
  try{
    const d=await pollJobs();
    if(d&&d.active){ await loadOverviewSummary(); annotatePipeline((d.jobs||[]).find(j=>j.job_id===d.active)); }
    else{ stopJobPolling(); await loadOverviewSummary(); await loadDatasets(); _watchJob=null; }
  } finally { _pollBusy=false; }
}
function startJobPolling(){ if(_jobTimer) return; pollTick(); _jobTimer=setInterval(pollTick,1500); }
function stopJobPolling(){ if(_jobTimer){ clearInterval(_jobTimer); _jobTimer=null; } }

function annotatePipeline(job){
  if(!job) return; const lbl=STEP_PIPELINE[job.step]; if(!lbl) return;
  const pr=job.progress, badge=` · 실행중${pr?` ${pr.done}/${pr.total}`:''} ${job.elapsed_s||0}s`;
  document.querySelectorAll('#pipelinebars .pl').forEach(pl=>{
    const l=pl.querySelector('.lbl');
    if(l&&l.textContent.trim()===lbl){ const st=pl.querySelector('.st'); if(st){ st.textContent='진행중'+badge; st.style.color='var(--orange)'; } const seg=pl.querySelector('.seg'); if(seg) seg.style.background='var(--orange)'; }
  });
}

const _rerunBtn=gid('rerunBtn'); if(_rerunBtn) _rerunBtn.addEventListener('click',doRerun);
loadDatasets();
pollJobs().then(d=>{ if(d&&d.active) startJobPolling(); });
