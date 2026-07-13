// ---------- language ----------
let uiLanguage=localStorage.getItem('poi-ui-language')||'ko';
const I18N={
  ko:{appSubtitle:'데이터 상태 확인 → 알고리즘 실행 → 결과·실패 케이스 분석',tabOverview:'개요',tabRun:'알고리즘 실행',tabResults:'실행 결과',tabData:'데이터셋 관리',resultsIntro:'실행 결과는 이곳에서 관리합니다. 실행을 하나 선택해 설정과 실패를 확인하고, 최대 4개 실행을 비교하거나 필요 없는 실행을 삭제하세요.',savedRuns:'저장된 실행',compareSelect:'비교 선택 (최대 4개)',runDetailEmpty:'왼쪽에서 실행을 선택하세요. 설정, 측정 결과, 필터 가능한 실패 케이스를 표시합니다.',selectedCompare:'선택 실행 비교',compareHelp:'막대는 정확도입니다. 아래 색 띠는 정답, 예측 없음(제출값 비어 있음), 오류, 오답의 구성입니다. 예측 없음은 코드가 빈 예측값을 반환한 경우이며, 실행 오류와는 별도로 집계합니다. 같은 코드 해시는 같은 제출 코드의 재실행을 뜻합니다.',retrievalDiagnostics:'후보 검색 진단',retrievalDiagnosticsHelp:'- 알고리즘 실행 결과와 별개인 후보 공급원 상태'},
  en:{appSubtitle:'Check data health → run an algorithm → inspect results and failures',tabOverview:'Overview',tabRun:'Run algorithm',tabResults:'Run results',tabData:'Dataset management',resultsIntro:'Manage persisted results here. Select one run to inspect its configuration and failures, compare up to four runs, or remove an obsolete result.',savedRuns:'Saved runs',compareSelect:'Compare (up to 4)',runDetailEmpty:'Select a run on the left. Its configuration, measured outcomes, and filterable failures appear here.',selectedCompare:'Compare selected runs',compareHelp:'Bars show accuracy. The colored strip breaks down correct, abstained (no prediction submitted), errored, and wrong cases. Abstentions are distinct from execution errors. Matching code hashes mean the same submission was run again.',retrievalDiagnostics:'Retrieval diagnostics',retrievalDiagnosticsHelp:'- candidate-provider health, separate from algorithm results'}
};
function applyLanguage(){document.documentElement.lang=uiLanguage;document.querySelectorAll('[data-i18n]').forEach(el=>{el.textContent=I18N[uiLanguage][el.dataset.i18n]||el.textContent});document.querySelectorAll('[data-lang]').forEach(b=>b.classList.toggle('on',b.dataset.lang===uiLanguage));if(selectedRun)renderRunDetail();}
document.querySelectorAll('[data-lang]').forEach(b=>b.onclick=()=>{uiLanguage=b.dataset.lang;localStorage.setItem('poi-ui-language',uiLanguage);applyLanguage()});

// ---------- tabs ----------
document.querySelectorAll(".tabs button").forEach(b=>b.onclick=()=>{
  document.querySelectorAll(".tabs button").forEach(x=>x.classList.toggle("on",x===b));
  document.querySelectorAll(".view").forEach(v=>v.classList.toggle("on", v.id==="v-"+b.dataset.t));
});

// ---------- eval (live /api/matchrate) ----------
const $=s=>document.querySelector(s);
let apiFailures=new Set();
let storeDataState=null;
function setApiState(key,error){
  if(error) apiFailures.add(key); else apiFailures.delete(key);
  const health=$('#apiHealth'), box=$('#apiError'), text=$('#apiErrorText');
  if(apiFailures.size){
    health.className='health err'; health.textContent='데이터 연결 오류';
    box.classList.add('on'); text.textContent='일부 데이터를 불러오지 못했습니다. 서버가 실행 중인지 확인한 뒤 다시 시도하세요.';
  }else{
    health.className='health ok';
    health.textContent=storeDataState==='empty'?'API 연결됨 · 데이터 없음':'실데이터 연결됨';
    box.classList.remove('on');
  }
}
async function apiJSON(url,key){
  try{const r=await fetch(url,{cache:'no-store'});if(!r.ok)throw new Error(`HTTP ${r.status}`);const d=await r.json();setApiState(key,null);return d;}
  catch(e){setApiState(key,e);throw e;}
}
$('#retryLoad').onclick=()=>loadAll();
let scope="all",mode="raw";
async function render(){
  const apiMode='exact';
  let d;
  try{d=await apiJSON(`/api/matchrate?dataset=${encodeURIComponent(scope)}&mode=${apiMode}`,'matchrate');}
  catch(e){d={n:0,rank1:0,top3:0,top5:0,top10:0,top20:0,top50:0,miss:0,counts:{},by_provider:{},matching_policy:{}};}
  const n=d.n||0, pct=x=>n?Math.round(100*x/n):0;
  const c=d.counts||{}, rows=c.rows||0;
  const excl=[]; if(d.excluded_korea_pending_kakao)excl.push(`KR/Kakao 대기 ${d.excluded_korea_pending_kakao}`); if(d.excluded_non_poi)excl.push(`non_poi ${d.excluded_non_poi}`); if(d.excluded_non_mapkit)excl.push(`NON_MAPKIT ${d.excluded_non_mapkit}`); if(d.excluded_sim_mapkit)excl.push(`SIM_MAPKIT ${d.excluded_sim_mapkit}`); if(d.excluded_no_gt)excl.push(`provider GT 없음 ${d.excluded_no_gt}`); if(d.no_provider_data)excl.push(`후보 데이터 없음 ${d.no_provider_data}`);
  $("#meta").innerHTML=d.counts&&d.counts.rows===0
    ? '등록된 데이터셋이 없습니다. ④ 데이터셋 관리에서 ZIP을 추가하면 평가 지표와 케이스가 표시됩니다.'
    : `대상 행 <b>${rows}</b> · canonical GT <b>${c.gt_canonical||0}</b> · 평가 완료 <b>n=${n}</b> · 제외/대기: ${excl.join(' · ')||'-'}<br>매칭: <b>동일 provider canonical name == candidate name</b> · sentinel/빈 provider GT는 정답 문자열이 아니라 홀드아웃 · 후보공급원: 현재 KR 제외 / non-KR=MapKit`;
  const set=(id,c)=>{$("#p-"+id).textContent=pct(c)+"%";$("#c-"+id).textContent=c+" / "+n;};
  set("r1",d.rank1||0);set("t3",d.top3||0);set("t5",d.top5||0);set("t10",d.top10||0);set("t20",d.top20||0);set("t50",d.top50||0);set("miss",d.miss||0);
  $("#flip").classList.add("hidden");
  drawCurve([[1,pct(d.rank1||0)],[3,pct(d.top3||0)],[5,pct(d.top5||0)],[10,pct(d.top10||0)],[20,pct(d.top20||0)],[50,pct(d.top50||0)]]);
}
function drawCurve(points){
  const W=580,H=260,pl=44,pr=16,pt=16,pb=32,xs=points.map(p=>p[0]);
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
    g+=`<text x="${cx}" y="${H-22}" text-anchor="middle" fill="var(--ink2)" font-size="11.5">${esc(name)}</text>`;
  });
  $("#bars").innerHTML=g;
}
// ---------- case analysis (real /api/records) ----------
const esc=s=>String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const plain=s=>esc(String(s==null?'':s).replace(/<[^>]*>/g,''));
let CASES=[],curOutcome='all',curCaseIdx=null;
const OC_LABEL={correct:'rank1',selection:'rank>1',retrieval:'검색실패',non_poi:'non_poi',deferred:'deferred',no_gt:'no_gt',other:'기타'};
const OC_ORDER=['all','correct','selection','retrieval','non_poi','deferred','no_gt'];
const providerExactEq=(a,b)=>{a=(a||'').trim();b=(b||'').trim();return !!(a&&b&&a===b);};
async function loadCases(){
  try{CASES=await apiJSON(`/api/records?dataset=${encodeURIComponent(scope)}`,'records');if(!Array.isArray(CASES))throw new Error(CASES.error||'invalid records response');}
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
    `<div class="ci ${i===curCaseIdx?'sel':''}" data-i="${i}">${c.photo_url?`<img loading="lazy" src="${esc(c.photo_url)}" onerror="this.style.visibility='hidden'">`:'<span style="width:44px"></span>'}<span class="g">${esc(c.gt||'(GT 없음)')}</span><span class="oc ${c.outcome}">${esc(OC_LABEL[c.outcome]||c.outcome)}</span></div>`).join('')
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
    ${c.photo_url?`<img src="${esc(c.photo_url)}" onerror="this.style.display='none'">`:''}
    <div class="drow"><span class="lab">GT</span><span class="val gt">${esc(c.gt||'(없음)')}</span></div>
    <div class="drow"><span class="lab">MapKit 1위</span><span class="val">${esc(c.baseline_pick||'—')} <span style="color:var(--ink3)">(최근접 · rank ${esc(c.rank)})</span></span></div>
    <div class="expl" style="background:${E[0]}"><b>${OC_LABEL[c.outcome]}</b> — ${E[1]}</div>
    <div class="drow"><span class="lab">후보 top3</span><span class="val" style="flex:1">${cands||'<span style="color:var(--ink3)">없음</span>'}${(c.rank&&c.rank!=='MISS'&&!gtIn)?`<div style="color:var(--ink3);font-size:11px;margin-top:2px">※ GT는 rank ${esc(c.rank)} — 상위 3 밖 (전체 ${esc(c.n_wide)}개 중)</div>`:''}</span></div>
    <div class="drow"><span class="lab">OCR</span><span class="val" style="font-size:12px;color:${c.ocr_text?'var(--ink2)':'var(--ink3)'}">${esc(c.ocr_text||'(텍스트 없음)')}</span></div>
    <div class="drow"><span class="lab">좌표</span><span class="val" style="font-family:var(--mono);font-size:12px">${esc(c.lat)}, ${esc(c.lon)}</span></div>
    <div class="drow"><span class="lab">카테고리</span><span class="val">${esc(c.category)}</span></div>`;
  renderCaseList();
}
$("#scope").onchange=e=>{scope=e.target.value;curCaseIdx=null;render();loadCases();};

render();
loadCases();

// ---------- overview: row structure (라벨 컬럼 · 채움 · 입력벡터) — live /api/overview fill ----------

async function loadOverviewSummary(){
  const by=id=>document.getElementById(id);
  try{
    const d=await apiJSON('/api/overview','overview');
    const total=d.total||0;
    storeDataState=d.data_state||((total>0)?'ready':'empty');
    setApiState('overview',null);
    const pct=c=>total?Math.round(100*c/total):0;
    const color=v=>String(v||'var(--blue)').startsWith('var(')?v:`var(--${v})`;
    by('k-total').textContent=total;
    by('k-gt').textContent=d.gt_present||0;
    by('k-photo').textContent=d.photo_present||0;
    by('k-country').textContent=(d.countries||[]).length;
    by('overviewEmpty').style.display=storeDataState==='empty'?'block':'none';
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
let _openFieldGroup=null;
async function loadRowStruct(){
  try{_rowstruct=await apiJSON('/api/overview','overview');}catch(e){_rowstruct={};}
  const sel=$("#rowstruct-src");
  if(sel && !sel.dataset.init){
    const dss=_rowstruct.datasets||[];
    sel.innerHTML='<option value="__all">전체</option>'+dss.map(x=>`<option value="${esc(x)}">${esc(x)}</option>`).join('');
    sel.dataset.init='1';
    sel.addEventListener('change',()=>{renderRowStruct(); if(_openFieldGroup) loadFieldProfile(_openFieldGroup);});
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
    return `<tr data-group="${esc(s.group)}" tabindex="0" role="button" aria-label="${esc(s.group)} 값 상세 보기"><td class="nm3">${esc(s.group)}</td>
      <td class="rl" style="color:${rcolor}">${esc(s.role_label||s.role_key||'')}</td>
      <td><div class="fb2"><div class="mt2"><div class="mf2" style="width:${pct}%;background:${color}"></div></div><span class="mp2">${pct}%</span></div></td>
      <td class="m3">${plain(s.desc||'')} <span style="color:var(--ink3)">· 상세 보기</span></td></tr>`;
  }).join('');
  $("#rowstruct").querySelectorAll('tr[data-group]').forEach(row=>{
    const open=()=>loadFieldProfile(row.dataset.group);
    row.addEventListener('click',open);
    row.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();open();}});
  });
}
function fmtProfileNumber(n){return Number.isInteger(n)?String(n):Number(n).toLocaleString(undefined,{maximumFractionDigits:5});}
function profileBars(items){
  const max=Math.max(1,...items.map(x=>x.count||0));
  return `<div class="profile-bars">${items.map(x=>`<div class="profile-bar"><span title="${esc(x.value||x.label)}">${esc(x.value||x.label)}</span><div class="track"><div class="fill" style="width:${Math.round(100*(x.count||0)/max)}%;background:var(--cyan)"></div></div><b>${x.count}</b></div>`).join('')}</div>`;
}
async function loadFieldProfile(group){
  _openFieldGroup=group;
  const panel=$('#fieldprofile'),src=$('#rowstruct-src')?.value||'__all';
  document.querySelectorAll('#rowstruct tr[data-group]').forEach(r=>r.classList.toggle('selected',r.dataset.group===group));
  panel.classList.add('on'); panel.textContent='실제 값과 분포를 불러오는 중…';
  try{
    const d=await apiJSON(`/api/field-profile?group=${encodeURIComponent(group)}&dataset=${encodeURIComponent(src)}`,'field-profile');
    const card=(p)=>{
      const denom=d.total||0, fill=denom?Math.round(100*p.present/denom):0;
      const stats=[`유형 <b>${esc(p.kind_label)}</b>`,`채움 <b>${p.present}/${denom} (${fill}%)</b>`,`결측 <b>${p.missing}</b>`,`고유값 <b>${p.unique}</b>`];
      if(p.numeric)stats.push(`최소 <b>${fmtProfileNumber(p.numeric.min)}</b>`,`중앙 <b>${fmtProfileNumber(p.numeric.median)}</b>`,`최대 <b>${fmtProfileNumber(p.numeric.max)}</b>`);
      if(p.text)stats.push(`길이 <b>${p.text.min_length} · ${p.text.median_length} · ${p.text.max_length}자</b>`);
      const distribution=p.numeric?.histogram || p.date_counts || p.top;
      const title=p.numeric?'값 구간 분포':(p.kind==='text'?'반복된 값 (OCR/자유 텍스트는 대개 고유)':p.kind==='date'?'날짜별 값':'상위 값');
      return `<section><h4>${esc(p.column)} · ${esc(p.kind_label)}</h4><div class="profile-stats">${stats.map(x=>`<span class="profile-stat">${x}</span>`).join('')}</div>${distribution.length?`<h4>${title}</h4>${profileBars(distribution)}`:''}${p.samples.length?`<h4>실제 값 예시 (최대 5개)</h4><ul class="profile-samples">${p.samples.map(v=>`<li>${esc(v)}</li>`).join('')}</ul>`:''}</section>`;
    };
    panel.innerHTML=`<h3>${esc(group)} <span style="font:11px var(--mono);color:var(--ink3)">· ${src==='__all'?'전체':esc(src)} · ${d.total}행</span></h3>${d.columns.map(card).join('')}`;
  }catch(e){panel.textContent=`상세 값을 불러오지 못했습니다: ${e.message}`;}
}
loadOverviewSummary();
loadRowStruct();

// ---------- run workspace (live submission harness + persisted runs) ----------
const REG={};
let runsList=[];
let selectedRunId=null, selectedRun=null;
let runFailureDataset='all', runFailureKind='all', runFailurePage=0;
const RUN_FAILURE_PAGE_SIZE=12;
const comparedRunIds=new Set();
const g=id=>document.getElementById(id);
applyLanguage();
// 입력 파라미터 = 신호 + 추출 방법(provenance). methods[0]=현재, 그 외=대안(이후).
const PARAMS=[
  {k:"image", name:"이미지", methods:["원본 사진 (jpg)"], on:false},
  {k:"lat,lon", name:"좌표", methods:["EXIF GPS"], on:true},
  {k:"timestamp", name:"촬영 시각", methods:["EXIF DateTimeOriginal"], on:false},
  {k:"ocr_text", name:"OCR 텍스트", methods:["Vision VNRecognizeTextRequest","Tesseract (이후)","Google Vision (이후)"], on:true},
  {k:"vlm_caption", name:"VLM 설명", methods:["FastVLM-0.5B","LLaVA (이후)"], on:false},
  {k:"nearby_candidates", name:"주변 후보", methods:["MapKit MKLocalPointsOfInterest","Google Places (이후)","Kakao Local (이후)"], on:true, topk:[3,5,10,"전체"]},
  {k:"city,country,address", name:"역지오코딩", methods:["Apple CLGeocoder","Google Geocoding (이후)"], on:false},
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
  'image':['photo','case["photo"]'],
  'lat,lon':['lat, lon','case["lat"], case["lon"]'],
  'timestamp':['ts','case["timestamp"]'],
  'ocr_text':['ocr','case["ocr_text"]'],
  'vlm_caption':['vlm','case["vlm_caption"]'],
  'nearby_candidates':['cands','case["nearby_candidates"]'],
  'city,country,address':['geo','case["geocode"]'],
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
    `<tr><td class="name">${esc(r.name)}</td><td><code>v${esc(r.version)}</code></td><td><code>${esc(r.lang||'—')}</code></td><td><code>${esc((r.params||[]).length+'개')}</code></td><td>${esc(r.scope)}</td><td>${esc(r.accuracy_pct)}%</td><td><span class="stt ok">저장됨</span></td></tr>`).join('') : '<tr><td colspan="7" style="color:var(--ink3);font-size:12px">아직 제출된 알고리즘 실행 결과가 없습니다. 후보검색 평가는 ③ 탭의 실제 GT/MapKit rank만 표시합니다.</td></tr>';
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
g('loadExample').onclick=async()=>{
  const hint=g('runhint');
  try{
    const res=await fetch('/examples/baseline_nearest.py',{cache:'no-store'});
    if(!res.ok) throw new Error(`HTTP ${res.status}`);
    scriptText=await res.text(); scriptName='baseline_nearest.py'; scriptLang='python';
    g('filelabel').textContent='📎 baseline_nearest.py 예시 코드가 준비됨';
    document.querySelector('.filedrop').classList.add('has');
    g('tname').value='baseline-nearest'; updVer();
    hint.textContent='예시 코드 준비 완료. 데이터셋이 있으면 실행할 수 있습니다.';
  }catch(err){ hint.textContent=`예시 코드 로드 실패: ${err.message}`; }
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
function selectedCandidateLimit(){
  const row=[...document.querySelectorAll('.prow')].find(r=>PARAMS[+r.dataset.pi].k==='nearby_candidates');
  if(!row||!row.querySelector('input').checked)return null;
  const raw=(row.querySelector('.topk')?.value||'').replace('top ','');
  return raw==='전체'||!raw?null:Number(raw);
}
g('runbtn').onclick=async()=>{
  if(!scriptText){ g('runhint').textContent='먼저 predict() 스크립트를 첨부하세요.'; return; }
  const name=(g('tname').value||'').trim()||'algorithm';
  const scope=g('rscope').value, save=g('savemode').value;
  const body={name,scope,mode:'exact',save_mode:save,lang:scriptLang,params:selectedParams(),candidate_limit:selectedCandidateLimit(),script_text:scriptText};
  g('runbtn').disabled=true; g('runhint').textContent=`실행 중: ${name} (${scope}) …`;
  try{
    const res=await fetch('/api/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const data=await res.json();
    if(data.ok){
      const m=data.metrics||{};
      g('runhint').textContent=`완료: ${data.name} v${data.version} · 식별 정확도 ${m.accuracy_pct}% (${m.correct}/${m.n_eligible}, 예측 없음 ${m.abstained}, 오류 ${m.errored})`;
      await loadRuns();
    }else{
      g('runhint').textContent=`실패: ${data.error||'실행 오류'}`;
    }
  }catch(err){ g('runhint').textContent=`요청 실패: ${err.message}`; }
  finally{ g('runbtn').disabled=false; }
};
// live runs from /api/runs → 최근 실행 표 + 식별 정확도 막대(알고리즘별, 이름당 최신 버전)
function runKey(r){return `${r.name}__v${r.version}`}
function renderRunManager(){
 const host=g('runManagerList');if(!host)return;g('compareHint').textContent=`${comparedRunIds.size} / 4 선택`;
 host.innerHTML=runsList.length?runsList.map(r=>{const k=runKey(r),dups=runsList.filter(x=>x.script_sha256===r.script_sha256).length;return `<div class="runrow ${k===selectedRunId?'sel':''}" data-rkey="${esc(k)}"><div class="rt"><span>${esc(r.name)} v${r.version}</span><b>${r.accuracy_pct}%</b></div><div class="rm">${esc(r.created_at||'')} · ${esc(r.scope)} · ${esc((r.params||[]).join(', ')||'추가 신호 없음')} · 후보 ${r.candidate_limit==null?'전체':r.candidate_limit}${dups>1?' · 동일 코드 '+dups+'회':''}</div><label class="compare" style="margin:7px 0 0"><input type="checkbox" data-compare="${esc(k)}" ${comparedRunIds.has(k)?'checked':''}> 비교에 포함</label></div>`}).join(''):'<div style="color:var(--ink3);font-size:12px;padding:10px">저장된 실행이 없습니다.</div>';
 host.querySelectorAll('[data-rkey]').forEach(el=>el.onclick=e=>{if(!e.target.matches('input'))selectRun(el.dataset.rkey)});
 host.querySelectorAll('[data-compare]').forEach(el=>el.onchange=e=>{const k=e.target.dataset.compare;if(e.target.checked&&!comparedRunIds.has(k)&&comparedRunIds.size>=4){e.target.checked=false;alert('비교는 최대 4개 실행까지 선택할 수 있습니다.');return}e.target.checked?comparedRunIds.add(k):comparedRunIds.delete(k);renderRunManager();drawCompareBars()});drawCompareBars();
}
function drawCompareBars(){const svg=g('compareBars');if(!svg)return;const rs=runsList.filter(r=>comparedRunIds.has(runKey(r))),W=580,H=210,pl=42,pr=14,pt=15,pb=42;if(!rs.length){svg.innerHTML=`<text x="290" y="105" text-anchor="middle" fill="var(--ink3)" font-size="12" font-family="var(--mono)">실행을 1개 이상 비교 선택하세요</text>`;return}const y=v=>pt+(H-pt-pb)*(1-v/100),step=(W-pl-pr)/rs.length,bw=Math.min(95,step*.6);let out='';for(let v=0;v<=100;v+=25)out+=`<line x1="${pl}" y1="${y(v)}" x2="${W-pr}" y2="${y(v)}" stroke="rgba(255,255,255,.07)"/><text x="${pl-6}" y="${y(v)+4}" text-anchor="end" fill="var(--ink3)" font-size="10">${v}</text>`;rs.forEach((r,i)=>{const cx=pl+step*(i+.5),a=Number(r.accuracy_pct)||0,n=Number(r.n_eligible)||0;out+=`<rect x="${cx-bw/2}" y="${y(a)}" width="${bw}" height="${y(0)-y(a)}" rx="4" fill="var(--cyan)"/><text x="${cx}" y="${y(a)-6}" text-anchor="middle" fill="var(--ink)" font-size="11">${a}%</text>`;let x=cx-bw/2;[[r.correct,'var(--green)'],[r.abstained,'var(--orange)'],[r.errored,'var(--red)'],[Math.max(0,n-(r.correct||0)-(r.abstained||0)-(r.errored||0)),'var(--pink)']].forEach(([v,c])=>{const w=n?bw*v/n:0;out+=`<rect x="${x}" y="179" width="${w}" height="8" fill="${c}"/>`;x+=w});out+=`<text x="${cx}" y="199" text-anchor="middle" fill="var(--ink2)" font-size="10">${esc(r.name)} v${r.version}</text>`});svg.innerHTML=out}
async function selectRun(k){const r=runsList.find(x=>runKey(x)===k);if(!r)return;selectedRunId=k;runFailureDataset='all';runFailureKind='all';runFailurePage=0;renderRunManager();g('runDetail').textContent='실행 상세를 불러오는 중…';try{const d=await apiJSON(`/api/runs?name=${encodeURIComponent(r.name)}&version=${r.version}`,'run-detail');selectedRun=d.run;renderRunDetail()}catch(e){g('runDetail').textContent='실행 상세를 불러오지 못했습니다.'}}
function showRunCode(){
  if(!selectedRun)return;
  const L=uiLanguage==='ko', r=selectedRun, hash=r.script_sha256||'';
  g('codeModalTitle').textContent=`${r.name} v${r.version} · ${hash|| (L?'코드 식별값 없음':'no code identity')}`;
  g('codeModalContent').textContent=r.script_text|| (L?'이 레거시 실행에는 저장된 소스 코드가 없습니다.':'No source code was stored for this legacy run.');
  g('codeModal').classList.add('on');g('closeCodeModal').focus();
}
function closeRunCode(){g('codeModal').classList.remove('on')}
g('closeCodeModal').onclick=closeRunCode;
g('codeModal').onclick=e=>{if(e.target===g('codeModal'))closeRunCode()};
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeRunCode()});
function renderRunDetail(){
  const r=selectedRun,m=r.metrics||{},n=m.n_eligible||0,wrong=Math.max(0,n-(m.correct||0)-(m.abstained||0)-(m.errored||0));
  const L=uiLanguage==='ko', label=L?{del:'실행 삭제',created:'실행 시각',config:'설정',inputs:'입력',identity:'코드 식별',candidates:'후보',all:'전체',none:'추가 신호 없음',correct:'정답',abstained:'예측 없음(제출값 비어 있음)',errors:'오류',wrong:'오답',failures:'실패 케이스',total:'전체',matching:'필터 결과',allDatasets:'모든 데이터셋',allOutcomes:'모든 결과',previous:'이전',next:'다음',noFailures:'조건에 맞는 실패가 없습니다.',error:'오류'}:{del:'Delete run',created:'Created',config:'Config',inputs:'Inputs',identity:'Code identity',candidates:'candidates',all:'all',none:'none',correct:'correct',abstained:'no prediction submitted',errors:'errors',wrong:'wrong',failures:'Failures',total:'total',matching:'matching',allDatasets:'All datasets',allOutcomes:'All outcomes',previous:'Previous',next:'Next',noFailures:'No failures match these filters.',error:'Error'};
  const part=(v,c)=>n?`<span style="width:${100*v/n}%;background:${c}"></span>`:'';
  const allFails=(r.cases||[]).filter(c=>!c.correct);
  const datasets=[...new Set(allFails.map(c=>c.dataset).filter(Boolean))].sort();
  const kinds=[...new Set(allFails.map(c=>c.error?'error':(c.prediction?'wrong':'abstained')))];
  const filtered=allFails.filter(c=>(runFailureDataset==='all'||c.dataset===runFailureDataset)&&(runFailureKind==='all'||(c.error?'error':(c.prediction?'wrong':'abstained'))===runFailureKind));
  const pages=Math.max(1,Math.ceil(filtered.length/RUN_FAILURE_PAGE_SIZE));
  runFailurePage=Math.min(runFailurePage,pages-1);
  const shown=filtered.slice(runFailurePage*RUN_FAILURE_PAGE_SIZE,(runFailurePage+1)*RUN_FAILURE_PAGE_SIZE);
  const hash=r.script_sha256||'';
  const hashText=hash?`${hash.slice(0,12)}${r.script_sha256_derived?(L?' · 레거시 파생':' · legacy-derived'):''}`:(L?'사용 불가':'unavailable');
  const kindLabel={error:label.errors,wrong:label.wrong,abstained:label.abstained};
  const failRows=shown.map(c=>{const kind=c.error?'error':(c.prediction?'wrong':'abstained'),ctx=c.context||{};const title=ctx.input_place_name||c.gt||c.photo||'case';const location=[ctx.category,ctx.city,ctx.country].filter(Boolean).join(' · ');const prediction=c.error?`${label.error}: ${c.error}`:(c.prediction||label.abstained);const ocr=ctx.ocr_text?`<span class="failreason">OCR: ${esc(ctx.ocr_text)}</span>`:'';const coords=(ctx.lat&&ctx.lon)?`<span class="failmeta">${esc(ctx.lat)}, ${esc(ctx.lon)}</span>`:'';const image=c.photo_url?`<img class="failthumb" src="${esc(c.photo_url)}" alt="" loading="lazy">`:'<span class="failthumb"></span>';return `<div class="failrow">${image}<span><span class="failtitle">${esc(title)}</span><span class="failmeta">${esc(location||c.dataset||'—')}</span><span class="failreason">GT: ${esc(c.gt||'—')} → ${esc(prediction)}</span>${ocr}${coords}<span class="failmeta">${esc(c.photo||'')}</span></span><span class="oc ${kind==='error'?'retrieval':kind==='wrong'?'selection':'other'}">${esc(kindLabel[kind])}</span></div>`}).join('')||`<div>${label.noFailures}</div>`;
  g('runDetail').innerHTML=`<div style="display:flex;justify-content:space-between;gap:10px"><b style="color:var(--ink)">${esc(r.name)} v${r.version}</b><button class="btn danger" id="deleteRun">${label.del}</button></div><div class="dl"><b>${label.created}</b><span>${esc(r.created_at||'')}</span><b>${label.config}</b><span>${esc(r.scope)} · ${esc(r.mode)} · ${label.candidates} ${r.candidate_limit==null?label.all:r.candidate_limit}</span><b>${label.inputs}</b><span>${esc((r.params||[]).join(', ')||label.none)}</span><b>${label.identity}</b><span title="${esc(hash||(L?'스크립트 텍스트가 없어 코드 식별값을 만들 수 없습니다.':'No script text was available to derive an identity.'))}">${esc(hashText)} <button class="btn" type="button" id="viewRunCode">${L?'코드 보기':'View code'}</button></span></div><div><b style="color:var(--ink)">${m.accuracy_pct||0}% · ${m.correct||0}/${n}</b> ${label.correct}</div><div class="outcomes">${part(m.correct||0,'var(--green)')}${part(m.abstained||0,'var(--orange)')}${part(m.errored||0,'var(--red)')}${part(wrong,'var(--pink)')}</div><div style="font:11px var(--mono);color:var(--ink3)">${label.correct} ${m.correct||0} · ${label.abstained} ${m.abstained||0} · ${label.errors} ${m.errored||0} · ${label.wrong} ${wrong}</div><div class="casefail"><b style="color:var(--ink3)">${label.failures} · ${allFails.length} ${label.total}, ${filtered.length} ${label.matching}</b><div class="detail-filters"><select id="failureDataset"><option value="all">${label.allDatasets}</option>${datasets.map(x=>`<option value="${esc(x)}" ${x===runFailureDataset?'selected':''}>${esc(x)}</option>`).join('')}</select><select id="failureKind"><option value="all">${label.allOutcomes}</option>${kinds.map(x=>`<option value="${x}" ${x===runFailureKind?'selected':''}>${esc(kindLabel[x]||x)}</option>`).join('')}</select></div>${failRows}<div class="pager"><button id="failurePrev" ${runFailurePage===0?'disabled':''}>${label.previous}</button><span>${filtered.length?`${runFailurePage+1} / ${pages}`:'0 / 0'}</span><button id="failureNext" ${runFailurePage>=pages-1?'disabled':''}>${label.next}</button></div></div>`;
  g('deleteRun').onclick=()=>deleteSelectedRun(r);
  g('viewRunCode').onclick=showRunCode;
  g('failureDataset').onchange=e=>{runFailureDataset=e.target.value;runFailurePage=0;renderRunDetail()};
  g('failureKind').onchange=e=>{runFailureKind=e.target.value;runFailurePage=0;renderRunDetail()};
  g('failurePrev').onclick=()=>{runFailurePage--;renderRunDetail()};
  g('failureNext').onclick=()=>{runFailurePage++;renderRunDetail()};
}
async function deleteSelectedRun(r){if(!confirm(`실행 "${r.name}" v${r.version}을 영구 삭제할까요?\n\n저장된 실행 JSON과 케이스 결과만 삭제됩니다.`))return;try{const res=await fetch(`/api/runs?name=${encodeURIComponent(r.name)}&version=${r.version}`,{method:'DELETE'}),d=await res.json();if(!res.ok||!d.ok)throw Error(d.error||`HTTP ${res.status}`);comparedRunIds.delete(runKey(r));selectedRunId=null;selectedRun=null;g('runDetail').textContent='실행이 삭제되었습니다.';await loadRuns()}catch(e){alert('실행 삭제 실패: '+e.message)}}

async function loadRuns(){
  let payload;
  try{ payload=await apiJSON('/api/runs','runs'); }catch(e){ return; }
  const runs=Array.isArray(payload.runs)?payload.runs:[];
  Object.keys(REG).forEach(k=>delete REG[k]);
  runs.forEach(r=>{ (REG[r.name]=REG[r.name]||[]).push(r.version); });
  Object.values(REG).forEach(a=>a.sort((x,y)=>x-y));
  runsList=runs;
  renderRuns();updVer();
  // one bar per algorithm name, latest version wins
  const latest={};
  runs.forEach(r=>{ if(!latest[r.name]||r.version>latest[r.name].version) latest[r.name]=r; });
  drawBars(Object.values(latest).sort((a,b)=>b.accuracy_pct-a.accuracy_pct).map(r=>[`${r.name} v${r.version}`,r.accuracy_pct]));
  if(selectedRunId&&!runs.some(r=>runKey(r)===selectedRunId)){ selectedRunId=null; selectedRun=null; }
  renderRunManager();
}
renderParams();updVer();loadRuns();

// ================= ④ dataset management + jobs + ① live progress =================
const gid=id=>document.getElementById(id);
let _dsData=null, _jobTimer=null, _watchJob=null, _pollBusy=false;
// step -> ① 신호 파이프라인 row label to annotate while running
const STEP_PIPELINE={ocr:'Vision OCR', mapkit_nearby:'MapKit 베이스라인', gt_mapkit:'MapKit 정규명(GT)'};

async function loadDatasets(){
  let d; try{ d=await apiJSON('/api/datasets','datasets'); }catch(e){ return; }
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
  const hasData=(d.datasets||[]).length>0;
  gid('rerunDataset').disabled=!hasData;
  gid('rerunStep').disabled=!hasData;
  gid('rerunBtn').disabled=!hasData;
  g('runbtn').disabled=!hasData;
  if(!hasData){
    gid('rerunHint').textContent='먼저 데이터셋을 추가하세요.';
    g('runhint').textContent='등록된 데이터셋이 없어 실행할 수 없습니다. 예시 코드는 미리 불러올 수 있습니다.';
  }else if(g('runhint').textContent.startsWith('등록된 데이터셋이 없어')){
    g('runhint').textContent='';
  }
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
  let d; try{ d=await apiJSON('/api/jobs','jobs'); }catch(e){ return null; }
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
const _ingestZip=gid('ingestZip');
if(_ingestZip) _ingestZip.onchange=async e=>{
  const f=e.target.files[0]; if(!f) return; const st=gid('uploadStatus');
  st.textContent=`추가 중 (ingest): ${f.name} … 업로드`;
  try{
    const res=await fetch('/api/ingest',{method:'POST',body:f,headers:{'Content-Type':'application/zip'}});
    const d=await res.json();
    if(!d.ok){ st.textContent='추가 실패: '+(res.status===409?'다른 작업 실행중':(d.error||res.status)); if(res.status===409) pollJobs(); }
    else { st.textContent=`ingest 잡 시작됨 (${d.job_id}) — 작업 패널·① 개요에서 진행 확인`; watchJob(d.job_id); }
  }catch(err){ st.textContent='추가 요청 실패: '+err.message; }
  e.target.value='';
};
loadDatasets();
pollJobs().then(d=>{ if(d&&d.active) startJobPolling(); });
function loadAll(){ apiFailures.clear(); loadOverviewSummary(); loadRowStruct(); render(); loadCases(); loadRuns(); loadDatasets(); pollJobs(); }
