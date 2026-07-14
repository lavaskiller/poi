// ---------- language ----------
// Retain a valid previous choice, but make English the first-visit default.
const SUPPORTED_LANGUAGES=new Set(['en','ko']);
const LANGUAGE_STORAGE_KEY='poi-ui-language';
function normalizeLanguage(value){return SUPPORTED_LANGUAGES.has(value)?value:'en';}
function storedLanguage(){try{return normalizeLanguage(localStorage.getItem(LANGUAGE_STORAGE_KEY));}catch(_){return 'en';}}
function storeLanguage(value){try{localStorage.setItem(LANGUAGE_STORAGE_KEY,value);}catch(_){/* Storage can be unavailable in privacy contexts. */}}
let uiLanguage=storedLanguage();
const I18N={
  en:{
    appSubtitle:'Check data health → run an algorithm → inspect results and failures',tabOverview:'Overview',tabRun:'Run algorithm',tabResults:'Run results',tabData:'Dataset management',
    retry:'Retry',totalRows:'Total rows',rowsWithGt:'Rows with GT labels',rowsWithPhotos:'Rows with photo references',countries:'Countries',overviewEmpty:'<b>No dataset has been added yet.</b> The API is connected. Validate and add a ZIP under Dataset management to enable evaluation.',provenance:'Provenance',confidenceTier:'Confidence tier (scoring)',signalPipeline:'Signal pipeline',rowStructure:'Row structure — label columns, coverage, and input vector',coverageByDataset:'Coverage by dataset',field:'Field',role:'Role',coverage:'Coverage',extractionMethod:'Extraction method',coverageHelp:'<b>Coverage determines algorithm-input availability.</b> Selecting sparse signals reduces eligible rows and the performance ceiling.',
    runIntro:'Upload a script that implements one prediction function. It runs against the evaluation set and saves the scored result under Run results.',runSettings:'Run settings',runName:'Run name',saveModeScope:'Save mode and scope',saveAuto:'Automatic (next version)',overwriteV1:'Overwrite v1',overwriteV2:'Overwrite v2',selectInputs:'Select inputs',selectInputsHelp:'— values passed to the function, extraction method, and candidate limit',usage:'Usage',usageHelp:'— access the selected inputs in your script',predictionFunction:'Prediction function',attachFileTypes:'— upload .py, .c, .cpp, .rs, .js, or .sh',attachScript:'📎 Upload a script that implements predict — click or drop',loadExample:'Load example code',downloadExample:'Download example .py',exampleHelp:'Minimal example that returns the nearest candidate',contract:'Contract',otherLanguages:'other languages read JSON from stdin and write the prediction to stdout',runAction:'▶ Run',recentRuns:'Recent runs',versioningHelp:'— matching names are versioned automatically',name:'Name',version:'Version',script:'Script',inputs:'Inputs',scope:'Scope',all:'All',status:'Status',
    resultsIntro:'Manage persisted results here. Select a run to inspect it, compare up to four runs, or delete it.',savedRuns:'Saved runs',compareSelect:'Compare (up to 4)',runDetailEmpty:'Select a run on the left to view its configuration, metrics, and failures.',selectedCompare:'Compare selected runs',compareHelp:'Bars show accuracy. The strip below each bar shows correct, no-prediction, error, and wrong cases.',retrievalDiagnostics:'Retrieval diagnostics',retrievalDiagnosticsHelp:'— candidate-provider coverage, separate from algorithm results',matching:'Matching',candidateRank1:'Candidate rank 1 · GT is first',candidateTop3:'Candidate top 3 · includes GT',candidateTop5:'Candidate top 5 · includes GT',candidateTop10:'Candidate top 10 · includes GT',candidateTop20:'Candidate top 20 · includes GT',candidateTop50:'Candidate top 50 · includes GT',candidateMiss:'Miss · GT absent from candidates',retrievalCoverage:'Retrieval coverage — top N by candidate provider',currentProvider:'current provider',curveAxes:'y = GT present in top-N candidates<br>x = N (measured ranks)',retrievalNote:'<b>Retrieval only.</b> This measures whether the provider returned the GT place. It is a coverage ceiling, not algorithm accuracy.',selectionAccuracy:'Selection accuracy by algorithm',selectionNote:'<b>Each bar is a submitted algorithm.</b> It shows exact-match accuracy for the latest version of each run name.',caseAnalysis:'Case analysis — retrieval success and failure',caseAnalysisHelp:'· live data · provider rank',selectCase:'Select a case on the left.',caseHelp:'<b>Retrieval failure</b> means GT is absent from all candidates. <b>Rank &gt; 1</b> means GT was returned but was not first.',
    datasetIntro:'Review datasets, rerun extraction steps, or add and remove data.',datasets:'Datasets',datasetCoverageHelp:'— processing and result coverage',dataset:'Dataset',rows:'Rows',signalCoverage:'Processing and detection',loading:'Loading…',rerunStepTitle:'Rerun extraction',rerunStepHelp:'— process rows not yet attempted',step:'Step',emptyRowsOnly:'Unprocessed rows only',rerun:'▶ Rerun',jobLimitHelp:'Only one data job can run at a time. Unavailable steps are disabled.',jobs:'Jobs',jobsHelp:'— progress and logs',noActiveJob:'No active job.',elapsed:'Elapsed',result:'Result',addDataset:'Add a dataset',addDatasetHelp:'— upload a ZIP and track ingestion above',downloadTemplate:'Download template ZIP',validateZip:'Validate ZIP',ingestDataset:'＋ Add dataset',uploadHelp:'Validate a ZIP before adding it. Ingestion runs as a job; derived signals can be filled afterward with Rerun extraction.',footer:'POI evaluation dashboard',submittedCode:'Submitted algorithm code',close:'Close',dataConnectionError:'Data connection error',dataLoadError:'Some data could not be loaded. Check that the server is running, then try again.',apiConnectedEmpty:'API connected · no data',liveDataConnected:'Live data connected'
  },
  ko:{
    appSubtitle:'데이터 상태 확인 → 알고리즘 실행 → 결과 및 실패 사례 확인',tabOverview:'개요',tabRun:'알고리즘 실행',tabResults:'실행 결과',tabData:'데이터셋 관리',
    retry:'다시 시도',totalRows:'전체 행',rowsWithGt:'정답 라벨이 있는 행',rowsWithPhotos:'사진이 있는 행',countries:'국가',overviewEmpty:'<b>등록된 데이터셋이 없습니다.</b> 데이터셋 관리에서 ZIP을 검증하고 추가하면 평가를 시작할 수 있습니다.',provenance:'데이터 출처',confidenceTier:'신뢰도 등급',signalPipeline:'신호 처리 단계',rowStructure:'행 구조 — 라벨, 입력값, 데이터 채움률',coverageByDataset:'데이터셋별 채움률',field:'필드',role:'역할',coverage:'채움률',extractionMethod:'추출 방법',coverageHelp:'<b>채움률은 알고리즘이 사용할 수 있는 입력의 비율입니다.</b> 채움률이 낮은 신호를 선택하면 평가 가능한 행이 줄어듭니다.',
    runIntro:'예측 함수가 포함된 스크립트를 업로드하세요. 평가 데이터 전체에 실행한 뒤 채점 결과를 실행 결과에 저장합니다.',runSettings:'실행 설정',runName:'실행 이름',saveModeScope:'저장 방식 및 범위',saveAuto:'자동(다음 버전)',overwriteV1:'v1 덮어쓰기',overwriteV2:'v2 덮어쓰기',selectInputs:'입력 선택',selectInputsHelp:'— 함수에 전달할 값, 추출 방법, 후보 수',usage:'사용 방법',usageHelp:'— 스크립트에서 선택한 입력에 접근하는 방법',predictionFunction:'예측 함수',attachFileTypes:'— .py, .c, .cpp, .rs, .js, .sh 업로드',attachScript:'📎 predict를 구현한 스크립트를 클릭하거나 끌어다 놓으세요',loadExample:'예시 코드 불러오기',downloadExample:'예시 .py 다운로드',exampleHelp:'가장 가까운 후보를 반환하는 간단한 예시',contract:'입출력 규약',otherLanguages:'그 외 언어는 stdin으로 JSON을 읽고 stdout으로 예측값을 출력',runAction:'▶ 실행',recentRuns:'최근 실행',versioningHelp:'— 같은 이름은 자동으로 버전이 올라갑니다',name:'이름',version:'버전',script:'스크립트',inputs:'입력',scope:'범위',all:'전체',status:'상태',
    resultsIntro:'저장된 실행을 확인하고, 최대 4개까지 비교하거나 삭제할 수 있습니다.',savedRuns:'저장된 실행',compareSelect:'비교할 실행 선택(최대 4개)',runDetailEmpty:'왼쪽에서 실행을 선택하면 설정, 지표, 실패 사례를 볼 수 있습니다.',selectedCompare:'선택한 실행 비교',compareHelp:'막대는 정확도를, 아래 띠는 정답·예측 없음·오류·오답의 비율을 나타냅니다.',retrievalDiagnostics:'후보 검색 진단',retrievalDiagnosticsHelp:'— 알고리즘 결과와 별도로 후보 제공 범위를 확인합니다',matching:'일치 기준',candidateRank1:'후보 1위 · 정답이 첫 번째',candidateTop3:'상위 3개 후보 · 정답 포함',candidateTop5:'상위 5개 후보 · 정답 포함',candidateTop10:'상위 10개 후보 · 정답 포함',candidateTop20:'상위 20개 후보 · 정답 포함',candidateTop50:'상위 50개 후보 · 정답 포함',candidateMiss:'검색 실패 · 후보에 정답 없음',retrievalCoverage:'후보 검색 범위 — 제공자별 상위 N개',currentProvider:'현재 후보 제공자',curveAxes:'y = 상위 N개 후보에 정답이 있는 비율<br>x = N(실측 순위)',retrievalNote:'<b>후보 검색 지표입니다.</b> 제공자가 정답 장소를 반환했는지 보여 주며, 알고리즘 정확도가 아니라 선택 가능한 범위의 상한입니다.',selectionAccuracy:'알고리즘별 선택 정확도',selectionNote:'<b>막대 하나가 제출한 알고리즘 하나를 나타냅니다.</b> 실행 이름별 최신 버전의 완전 일치 정확도입니다.',caseAnalysis:'사례 분석 — 후보 검색 성공 및 실패',caseAnalysisHelp:'· 실제 데이터 · 후보 순위',selectCase:'왼쪽에서 사례를 선택하세요.',caseHelp:'<b>검색 실패</b>는 전체 후보에 정답이 없다는 뜻입니다. <b>순위 2위 이하</b>는 정답이 후보에 있지만 첫 번째가 아니라는 뜻입니다.',
    datasetIntro:'데이터셋을 확인하고 추출 단계를 다시 실행하거나 데이터를 추가·삭제할 수 있습니다.',datasets:'데이터셋',datasetCoverageHelp:'— 처리율·결과 검출률 및 관리',dataset:'데이터셋',rows:'행',signalCoverage:'처리 상태와 결과 검출',loading:'불러오는 중…',rerunStepTitle:'추출 다시 실행',rerunStepHelp:'— 아직 처리하지 않은 행 실행',step:'단계',emptyRowsOnly:'미처리 행만',rerun:'▶ 다시 실행',jobLimitHelp:'데이터 작업은 한 번에 하나만 실행할 수 있습니다. 사용할 수 없는 단계는 비활성화됩니다.',jobs:'작업',jobsHelp:'— 진행 상황 및 로그',noActiveJob:'실행 중인 작업이 없습니다.',elapsed:'경과 시간',result:'결과',addDataset:'새 데이터셋 추가',addDatasetHelp:'— ZIP을 업로드하고 위에서 진행 상황 확인',downloadTemplate:'템플릿 ZIP 다운로드',validateZip:'ZIP 검증',ingestDataset:'＋ 데이터셋 추가',uploadHelp:'추가하기 전에 ZIP을 검증하세요. 데이터 추가는 작업으로 실행되며, 파생 신호는 이후 추출 다시 실행에서 채울 수 있습니다.',footer:'POI 평가 대시보드',submittedCode:'제출한 알고리즘 코드',close:'닫기',dataConnectionError:'데이터 연결 오류',dataLoadError:'일부 데이터를 불러오지 못했습니다. 서버가 실행 중인지 확인한 뒤 다시 시도하세요.',apiConnectedEmpty:'API 연결됨 · 데이터 없음',liveDataConnected:'실데이터 연결됨'
  }
};
const tr=(key,fallback='')=>I18N[uiLanguage]?.[key]??I18N.en[key]??fallback;
const LABELS={
  en:{
    outcome:{correct:'rank 1',selection:'rank > 1',retrieval:'retrieval miss',non_poi:'not a POI',deferred:'deferred',no_gt:'no GT',other:'other',all:'All'},
    pipelineStatus:{done:'Done',run:'In progress',waiting:'Waiting'}, role:{in:'Input signal',gt:'Ground truth',bl:'Baseline',mt:'Metadata'},
    fieldKind:{coordinate:'Coordinate',number:'Number',date:'Date/time',asset:'File/URL',identifier:'Identifier',category:'Category',text:'Text',ocr:'OCR text'},
    jobStatus:{queued:'Queued',running:'Running',done:'Done',error:'Failed',cancelled:'Cancelled'},
    step:{exif:'EXIF coordinates and capture time',ocr:'OCR text',geocode:'Reverse geocoding',mapkit_nearby:'MapKit nearby candidates',gt_mapkit:'MapKit canonical name (GT)',gt_kakao:'Kakao canonical name (GT)',vlm_caption:'VLM caption',ingest:'Dataset ingestion',delete_dataset:'Delete dataset',pipeline:'Post-ingestion pipeline'},
    signalStatus:{ok:'Available','미구현':'Not implemented',disabled:'Disabled',unavailable:'Unavailable',error:'Error'},
    mapkitGt:{canonical:'Canonical',similar:'Similar',not_found:'Unregistered'}
  },
  ko:{
    outcome:{correct:'1위 일치',selection:'2위 이하',retrieval:'검색 실패',non_poi:'POI 아님',deferred:'보류',no_gt:'GT 없음',other:'기타',all:'전체'},
    pipelineStatus:{done:'완료',run:'진행 중',waiting:'대기'}, role:{in:'입력 신호',gt:'정답',bl:'기준 결과',mt:'메타데이터'},
    fieldKind:{coordinate:'좌표',number:'숫자',date:'날짜/시간',asset:'파일/URL',identifier:'식별자',category:'범주',text:'텍스트',ocr:'OCR 텍스트'},
    jobStatus:{queued:'대기',running:'실행 중',done:'완료',error:'실패',cancelled:'취소됨'},
    step:{exif:'EXIF 좌표 및 촬영 시각',ocr:'OCR 텍스트',geocode:'역지오코딩',mapkit_nearby:'MapKit 주변 후보',gt_mapkit:'MapKit 정규명(GT)',gt_kakao:'Kakao 정규명(GT)',vlm_caption:'VLM 설명',ingest:'데이터셋 추가',delete_dataset:'데이터셋 삭제',pipeline:'추가 후 처리'},
    signalStatus:{ok:'사용 가능','미구현':'미구현',disabled:'비활성','사용 불가':'사용 불가',unavailable:'사용 불가',error:'오류'},
    mapkitGt:{canonical:'정규명',similar:'유사명',not_found:'미등록'}
  }
};
const tl=(group,key,fallback='')=>LABELS[uiLanguage]?.[group]?.[key]??LABELS.en[group]?.[key]??fallback;
// Transitional helper for interpolated copy. New fixed labels belong in I18N.
const bi=(en,ko)=>uiLanguage==='ko'?ko:en;
function applyStaticLanguage(){
  document.documentElement.lang=uiLanguage;
  document.querySelectorAll('[data-i18n]').forEach(el=>{const value=tr(el.dataset.i18n);if(value!==undefined)el.innerHTML=value});
  document.querySelectorAll('[data-lang]').forEach(b=>b.classList.toggle('on',b.dataset.lang===uiLanguage));
  setApiState('language',null);
}
function renderLocalizedUI(){
  applyStaticLanguage();
  if(selectedRun)renderRunDetail();
  if(_rowstruct){const open=_openFieldGroup;renderRowStruct();if(open)loadFieldProfile(open);}
  renderParams();renderRuns();renderRunManager();drawCompareBars();renderChips();renderCaseList();
  if(curCaseIdx!=null)showCase(curCaseIdx);
  if(_matchrateData)render(_matchrateData);
  if(_overviewData)loadOverviewSummary(_overviewData);
  if(_dsData)loadDatasets(_dsData);
  if(_jobsData)pollJobs(_jobsData);
}
function setLanguage(value){uiLanguage=normalizeLanguage(value);storeLanguage(uiLanguage);renderLocalizedUI();}
document.querySelectorAll('[data-lang]').forEach(b=>b.onclick=()=>setLanguage(b.dataset.lang));

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
    health.className='health err'; health.textContent=tr('dataConnectionError');
    box.classList.add('on'); text.textContent=tr('dataLoadError');
  }else{
    health.className='health ok';
    health.textContent=tr(storeDataState==='empty'?'apiConnectedEmpty':'liveDataConnected');
    box.classList.remove('on');
  }
}
async function apiJSON(url,key){
  try{const r=await fetch(url,{cache:'no-store'});if(!r.ok)throw new Error(`HTTP ${r.status}`);const d=await r.json();setApiState(key,null);return d;}
  catch(e){setApiState(key,e);throw e;}
}
$('#retryLoad').onclick=()=>loadAll();
let scope="all",mode="raw";
let _matchrateData=null;
async function render(data=null){
  const apiMode='exact';
  let d=data;
  try{d=d||await apiJSON(`/api/matchrate?dataset=${encodeURIComponent(scope)}&mode=${apiMode}`,'matchrate');_matchrateData=d;}
  catch(e){d={n:0,rank1:0,top3:0,top5:0,top10:0,top20:0,top50:0,miss:0,counts:{},by_provider:{},matching_policy:{}};}
  const n=d.n||0, pct=x=>n?Math.round(100*x/n):0;
  const rows=(d.counts||{}).rows||0;
  $("#meta").innerHTML=d.counts&&d.counts.rows===0
    ? bi('No datasets yet. Add a ZIP under Dataset management to see evaluation metrics and cases.','등록된 데이터셋이 없습니다. 데이터셋 관리에서 ZIP을 추가하면 평가 지표와 사례를 볼 수 있습니다.')
    : bi(`Eligible rows <b>${rows}</b> · evaluated <b>${n}</b>`,`평가 대상 <b>${rows}</b>행 · 평가 완료 <b>${n}</b>행`);
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
    $("#bars").innerHTML=`<text x="${W/2}" y="${H/2-8}" text-anchor="middle" fill="var(--ink2)" font-size="13" font-family="var(--mono)">${bi('No algorithms submitted — upload predict() under Run algorithm','제출된 알고리즘이 없습니다 — 알고리즘 실행에서 predict()를 업로드하세요')}</text><text x="${W/2}" y="${H/2+16}" text-anchor="middle" fill="var(--ink3)" font-size="11.5">${bi('MapKit and Kakao provide candidates; they are not algorithm results.','MapKit과 Kakao는 후보 제공자이며 알고리즘 결과가 아닙니다.')}</text>`;
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
const outcomeLabel=o=>tl('outcome',o,o);
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
    `<span class="chip ${o===curOutcome?'on':''}" data-o="${o}">${outcomeLabel(o)}<span class="c">${outCount(o)}</span></span>`).join('');
  $("#chips").querySelectorAll('.chip').forEach(el=>el.onclick=()=>{curOutcome=el.dataset.o;renderChips();renderCaseList();});
}
function renderCaseList(){
  const list=CASES.map((c,i)=>[c,i]).filter(([c])=>curOutcome==='all'||c.outcome===curOutcome);
  $("#caselist").innerHTML=list.slice(0,200).map(([c,i])=>
    `<div class="ci ${i===curCaseIdx?'sel':''}" data-i="${i}">${c.photo_url?`<img loading="lazy" src="${esc(c.photo_url)}" onerror="this.style.visibility='hidden'">`:'<span style="width:44px"></span>'}<span class="g">${esc(c.gt||bi('(no GT)','(GT 없음)'))}</span><span class="oc ${c.outcome}">${esc(outcomeLabel(c.outcome))}</span></div>`).join('')
    || `<div style="color:var(--ink3);font-size:12px;padding:10px">${bi('No matching cases.','조건에 맞는 사례가 없습니다.')}</div>`;
  $("#caselist").querySelectorAll('.ci').forEach(el=>el.onclick=()=>showCase(+el.dataset.i));
}
function showCase(i){
  curCaseIdx=i;const c=CASES[i];
  const E={
    correct:['rgba(95,211,123,.1)',bi('The first MapKit candidate exactly matches the GT.','MapKit의 첫 번째 후보가 GT와 정확히 일치합니다.')],
    selection:['rgba(255,159,69,.1)',bi(`The GT is candidate <b>rank ${esc(c.rank)}</b>; MapKit ranked '<b>${esc(c.baseline_pick)}</b>' first. The algorithm can still select the GT.`,`GT는 후보 <b>${esc(c.rank)}위</b>이며 MapKit의 첫 번째 후보는 '<b>${esc(c.baseline_pick)}</b>'입니다. 알고리즘은 후보에서 GT를 선택할 수 있습니다.`)],
    retrieval:['rgba(255,107,92,.1)',bi(`The GT is absent from all ${esc(c.n_wide)} candidates within 250 m. Selection logic cannot recover it.`,`250m 내 후보 ${esc(c.n_wide)}개에 GT가 없습니다. 선택 알고리즘으로는 해결할 수 없습니다.`)],
    non_poi:['rgba(118,131,184,.1)',bi('Not a POI; the correct action is to reject it.','POI가 아니므로 거절이 정답입니다.')],
    deferred:['rgba(118,131,184,.1)',bi('Baseline evaluation was deferred.','베이스라인 평가가 보류되었습니다.')],
    no_gt:['rgba(118,131,184,.1)',bi('No GT label is available.','GT 라벨이 없습니다.')],
  }[c.outcome]||['rgba(118,131,184,.1)',''];
  const gtIn=(c.candidates||[]).some(cd=>providerExactEq(cd.name,c.gt));
  const cands=(c.candidates||[]).map(cd=>{
    const isgt=providerExactEq(cd.name,c.gt),ispick=providerExactEq(cd.name,c.baseline_pick);
    const tags=(isgt?'<span class="tg" style="background:rgba(95,211,123,.2);color:var(--green)">GT</span>':'')+(ispick?`<span class="tg" style="background:rgba(255,159,69,.2);color:var(--orange)">${bi('MapKit rank 1','MapKit 1위')}</span>`:'');
    return `<div class="cand ${isgt?'isgt':''} ${ispick?'ispick':''}"><span>${esc(cd.name)}</span><span><span style="color:var(--ink3);font-family:var(--mono);font-size:11px">${esc(cd.dist)}</span>${tags}</span></div>`;
  }).join('');
  $("#casedetail").innerHTML=`
    ${c.photo_url?`<img src="${esc(c.photo_url)}" onerror="this.style.display='none'">`:''}
    <div class="drow"><span class="lab">GT</span><span class="val gt">${esc(c.gt||bi('(none)','(없음)'))}</span></div>
    <div class="drow"><span class="lab">${bi('MapKit rank 1','MapKit 1위')}</span><span class="val">${esc(c.baseline_pick||'—')} <span style="color:var(--ink3)">(${bi('nearest','최근접')} · rank ${esc(c.rank)})</span></span></div>
    <div class="expl" style="background:${E[0]}"><b>${outcomeLabel(c.outcome)}</b> — ${E[1]}</div>
    <div class="drow"><span class="lab">${bi('Top 3 candidates','상위 3개 후보')}</span><span class="val" style="flex:1">${cands||`<span style="color:var(--ink3)">${bi('None','없음')}</span>`}${(c.rank&&c.rank!=='MISS'&&!gtIn)?`<div style="color:var(--ink3);font-size:11px;margin-top:2px">${bi(`GT is rank ${esc(c.rank)}, outside the top 3 of ${esc(c.n_wide)} candidates.`,`GT는 ${esc(c.rank)}위로 전체 후보 ${esc(c.n_wide)}개 중 상위 3개 밖에 있습니다.`)}</div>`:''}</span></div>
    <div class="drow"><span class="lab">OCR</span><span class="val" style="font-size:12px;color:${c.ocr_text?'var(--ink2)':'var(--ink3)'}">${esc(c.ocr_text||bi('(no text)','(텍스트 없음)'))}</span></div>
    <div class="drow"><span class="lab">${bi('Coordinates','좌표')}</span><span class="val" style="font-family:var(--mono);font-size:12px">${esc(c.lat)}, ${esc(c.lon)}</span></div>
    <div class="drow"><span class="lab">${bi('Category','카테고리')}</span><span class="val">${esc(c.category)}</span></div>`;
  renderCaseList();
}
$("#scope").onchange=e=>{scope=e.target.value;curCaseIdx=null;render();loadCases();};

render();
loadCases();

// ---------- overview: row structure (라벨 컬럼 · 채움 · 입력벡터) — live /api/overview fill ----------

const PIPELINE_LABELS_EN={'GPS 좌표':'GPS coordinates','사진 다운로드+변환':'Photo download and conversion','입력 장소명':'Input place name','MapKit 베이스라인':'MapKit baseline','MapKit 정규명(GT)':'MapKit canonical name (GT)','온디바이스 LLM (v2)':'On-device LLM (v2)','FastVLM (이미지)':'FastVLM (image)'};
let _overviewData=null;
const pipelineLabel=label=>uiLanguage==='ko'?(label||'처리 단계'):(PIPELINE_LABELS_EN[label]||(!hasKorean(label)?label:'Pipeline step'));
async function loadOverviewSummary(data=null){
  const by=id=>document.getElementById(id);
  try{
    const d=data||await apiJSON('/api/overview','overview');
    _overviewData=d;
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
    by('sourcebars').innerHTML=(d.sources||[]).map(x=>`<div class="src"><span class="dot" style="background:${color(x.color)}"></span><span>${esc(x.key)}</span><b>${x.count}</b></div>`).join('');
    by('confidencebars').innerHTML=(d.confidence||[]).map(x=>`<div class="bar"><span class="lbl">${esc(x.key)}</span><div class="track"><div class="fill" style="width:${pct(x.count)}%;background:${color(x.color)}"></div></div><span class="v">${x.count}</span></div>`).join('');
    by('countrybars').innerHTML=(d.countries||[]).map((x,i)=>`<div class="bar"><span class="lbl">${esc(x.flag||'·')} ${esc(x.key)}</span><div class="track"><div class="fill" style="width:${pct(x.count)}%;background:${['var(--blue)','var(--pink)','var(--cyan)','var(--violet)','var(--orange)'][i%5]}"></div></div><span class="v">${x.count}</span></div>`).join('');
    by('pipelinebars').innerHTML=(d.pipeline||[]).map(x=>{const p=total?Math.round(100*(x.merged||x.extracted||0)/total):0;const st=tl('pipelineStatus',x.status==='done'?'done':(x.status==='run'?'run':'waiting'));const label=pipelineLabel(x.label);const col=x.status==='done'?'var(--green)':(x.status==='run'?'var(--orange)':'#333c66');return `<div class="pl"><span class="lbl">${esc(label)}</span><div class="track"><div class="seg" style="width:${p}%;background:${col}"></div></div><span class="st ${x.status}">${st}</span></div>`}).join('');
  }catch(e){ console.warn('overview load failed',e); }
}
// Row structure is rendered live from /api/overview `schema` (config-driven).
// No hardcoded column list — schema_groups / CSV changes reflect on reload.
// The 출처(dataset) dropdown recomputes 채움% from per-dataset fills.
let _rowstruct=null;
let _openFieldGroup=null;
const FIELD_DESC_EN={'capture_lat/lon':'Photo EXIF GPS coordinates.','caption_ondevice':'Text extracted from photos with Vision OCR.','photo_url / photo':'S3 URL and local filename; input for FastVLM and OCR.','timestamp':'Capture time retained only for the local dataset.','input_place_name':'Raw user input before provider normalization.','gt_mapkit':'Canonical MapKit answer for non-Korean rows; used for scoring.','gt_kakao':'Canonical Kakao answer for Korean rows; held out until Kakao data is available.','gt_confidence':'Label confidence tier.','category':'POI type used for failure analysis.','city / country / address':'Reverse-geocoded strings supplied by exports.','app_poi_rank':'Rank of the correct answer in the current app MapKit search.','app_nearby_top1':'Nearest result within a 250 m MapKit radius.','app_nearby_n_wide':'Number of candidates within the wider MapKit radius.','app_poi_dist_m':'Distance to the matched POI, in metres.','baseline_place_title':'Title attached by the app.','poi_match_keyword':'Keyword used to find the answer in MapKit results.','poi_list_match':'Answer-match detail and annotations.','dataset / notes / username':'Dataset identity and internal annotations.','caption_oracle':'Strong vision-model captions deliberately removed to prevent circularity.'};
const FIELD_LABELS={en:{'dataset / notes / username':'Dataset metadata'},ko:{'dataset / notes / username':'데이터셋 메타데이터'}};
const fieldLabel=group=>FIELD_LABELS[uiLanguage]?.[group]||group;

async function loadRowStruct(data=_overviewData){
  try{_rowstruct=data||await apiJSON('/api/overview','overview');}catch(e){_rowstruct={};}
  const sel=$("#rowstruct-src");
  if(sel && !sel.dataset.init){
    const dss=_rowstruct.datasets||[];
    sel.innerHTML=`<option value="__all">${uiLanguage==='en'?'All':'전체'}</option>`+dss.map(x=>`<option value="${esc(x)}">${esc(x)}</option>`).join('');
    sel.dataset.init='1';
    sel.addEventListener('change',()=>{renderRowStruct(); if(_openFieldGroup) loadFieldProfile(_openFieldGroup);});
  }
  renderRowStruct();
}
function renderRowStruct(){
  const d=_rowstruct||{},schema=d.schema||[];
  const sel=$("#rowstruct-src"),src=sel?sel.value:'__all',isAll=src==='__all';
  if(sel&&sel.options.length)sel.options[0].textContent=uiLanguage==='en'?'All':'전체';
  const total=isAll?Number(d.total||0):Number((d.total_by_dataset||{})[src]||0);
  const fbd=isAll?null:((d.fill_by_dataset||{})[src]||{});
  const RC={in:'var(--blue)',gt:'var(--gold)',bl:'var(--green)',mt:'var(--ink3)'};
  $("#rowstruct").innerHTML=schema.map(s=>{
    const rep=(s.cols&&s.cols[0])||'';
    const f=isAll?Number(s.fill||0):Number(fbd[rep]||0);
    const pct=total?Math.round(100*f/total):0;
    const color=pct>=90?'var(--green)':(pct===0?'var(--ink3)':'var(--orange)');
    const rcolor=RC[s.role_key]||'var(--ink3)';
    return `<tr data-group="${esc(s.group)}" tabindex="0" aria-label="${esc(fieldLabel(s.group))} ${uiLanguage==='en'?'details':'값 상세 보기'}"><td class="nm3">${esc(fieldLabel(s.group))}</td>
      <td class="rl" style="color:${rcolor}">${esc(tl('role',s.role_key,s.role_key||''))}</td>
      <td><div class="fb2"><div class="mt2"><div class="mf2" style="width:${pct}%;background:${color}"></div></div><span class="mp2">${pct}%</span></div></td>
      <td class="m3">${uiLanguage==='en'?esc(FIELD_DESC_EN[s.group]||(s.desc&&!/[가-힣]/.test(s.desc)?String(s.desc).replace(/<[^>]*>/g,''):'No description is available for this field.')):plain(s.desc||'')} <button class="field-detail-trigger" type="button" aria-label="${esc(fieldLabel(s.group))} ${uiLanguage==='en'?'details':'값 상세 보기'}">${uiLanguage==='en'?'Details':'상세 보기'}</button></td></tr>`;
  }).join('');
  $("#rowstruct").querySelectorAll('tr[data-group]').forEach(row=>{
    const open=()=>loadFieldProfile(row.dataset.group);
    row.addEventListener('click',open);
    row.addEventListener('keydown',e=>{if(e.target===row&&(e.key==='Enter'||e.key===' ')){e.preventDefault();open();}});
  });
  $("#rowstruct").querySelectorAll('.field-detail-trigger').forEach(button=>{
    button.addEventListener('click',e=>{e.stopPropagation();loadFieldProfile(button.closest('tr').dataset.group);});
  });
}
function fmtProfileNumber(n){return Number.isInteger(n)?String(n):Number(n).toLocaleString(undefined,{maximumFractionDigits:5});}
function profileBars(items){
  const max=Math.max(1,...items.map(x=>x.count||0));
  return `<div class="profile-bars">${items.map(x=>`<div class="profile-bar"><span title="${esc(x.value||x.label)}">${esc(x.value||x.label)}</span><div class="track"><div class="fill" style="width:${Math.round(100*(x.count||0)/max)}%;background:var(--cyan)"></div></div><b>${x.count}</b></div>`).join('')}</div>`;
}
function profileCompleteness(p,total){
  const L=uiLanguage==='en';
  const pct=total?Math.round(100*p.present/total):0, circumference=251.2, dash=(circumference*pct/100).toFixed(1);
  const kind=tl('fieldKind',p.kind,p.kind_label);
  return `<div class="profile-summary"><svg class="profile-completeness" viewBox="0 0 100 100" aria-label="${pct}% ${L?'populated':'채워짐'}"><circle class="base" cx="50" cy="50" r="40"/><circle class="value" cx="50" cy="50" r="40" transform="rotate(-90 50 50)" stroke-dasharray="${dash} ${circumference}"></circle><text x="50" y="55" text-anchor="middle">${pct}%</text></svg><div class="profile-overview"><b>${p.present} ${L?'populated':'채워짐'} · ${p.missing} ${L?'missing':'비어 있음'}</b><span>${p.unique} ${L?`distinct value${p.unique===1?'':'s'}`:'고유값'} · ${esc(kind)}</span>${p.numeric?`<span>${L?'Range':'범위'} ${fmtProfileNumber(p.numeric.min)} — ${fmtProfileNumber(p.numeric.max)} · ${L?'median':'중앙값'} ${fmtProfileNumber(p.numeric.median)}</span>`:''}${p.text?`<span>${L?'Text length':'텍스트 길이'}: ${p.text.min_length} — ${p.text.max_length} · ${L?'median':'중앙값'} ${p.text.median_length}</span>`:''}</div></div>`;
}
function profileHistogram(items){
  const max=Math.max(1,...items.map(x=>x.count||0));
  const L=uiLanguage==='en';
  return `<div class="profile-histogram">${items.map(x=>`<div class="profile-hist-bin" title="${esc(x.label)}: ${x.count}"><i style="height:${Math.max(3,Math.round(100*x.count/max))}%"></i><span>${esc(x.label)}</span></div>`).join('')}</div><div class="profile-chart-label"><span>${L?'Lower values':'낮은 값'}</span><span>${L?'Higher values':'높은 값'}</span></div>`;
}
async function loadFieldProfile(group){
  const existing=document.querySelector('.fieldprofile-row');
  if(_openFieldGroup===group && existing){
    existing.remove(); _openFieldGroup=null;
    document.querySelectorAll('#rowstruct tr[data-group]').forEach(r=>r.classList.remove('selected'));
    return;
  }
  _openFieldGroup=group;
  const src=$('#rowstruct-src')?.value||'__all', tbody=$('#rowstruct');
  document.querySelectorAll('#rowstruct tr[data-group]').forEach(r=>r.classList.toggle('selected',r.dataset.group===group));
  document.querySelectorAll('.fieldprofile-row').forEach(r=>r.remove());
  const anchor=tbody.querySelector(`tr[data-group="${CSS.escape(group)}"]`);
  if(!anchor)return;
  const detail=document.createElement('tr'); detail.className='fieldprofile-row'; detail.innerHTML=`<td colspan="4"><div class="fieldprofile" aria-live="polite">${uiLanguage==='en'?'Loading field profile…':'필드 상세 정보를 불러오는 중…'}</div></td>`;
  anchor.insertAdjacentElement('afterend',detail);
  const panel=detail.querySelector('.fieldprofile');
  try{
    const d=await apiJSON(`/api/field-profile?group=${encodeURIComponent(group)}&dataset=${encodeURIComponent(src)}`,'field-profile');
    const card=(p)=>{
      const denom=d.total||0, fill=denom?Math.round(100*p.present/denom):0;
      const distribution=p.numeric?.histogram || p.date_counts || p.top;
      const L=uiLanguage==='en', title=p.numeric?(L?'Distribution':'분포'):(p.kind==='text'?(L?'Most repeated values':'반복된 값'):(p.kind==='date'?(L?'Values by date':'날짜별 값'):(L?'Most frequent values':'자주 나타나는 값')));
      const chart=p.numeric?profileHistogram(distribution):(distribution.length?profileBars(distribution):`<div class="profile-empty">${L?'No populated values in this selection.':'선택한 범위에 채워진 값이 없습니다.'}</div>`);
      return `<section><h4>${esc(p.column)}</h4>${profileCompleteness(p,denom)}<h4>${title}</h4>${chart}${p.samples.length?`<h4>${L?'Example values':'예시 값'}</h4><ul class="profile-samples">${p.samples.map(v=>`<li>${esc(v)}</li>`).join('')}</ul>`:''}</section>`;
    };
    panel.innerHTML=`<h3>${esc(fieldLabel(group))} <span style="font:11px var(--mono);color:var(--ink3)">· ${src==='__all'?(uiLanguage==='en'?'All datasets':'전체 데이터셋'):esc(src)} · ${d.total}${uiLanguage==='en'?' rows':'행'}</span></h3>${d.columns.map(card).join('')}`;
  }catch(e){panel.textContent=uiLanguage==='en'?`Could not load the field profile: ${e.message}`:`필드 상세 정보를 불러올 수 없습니다: ${e.message}`;}
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
applyStaticLanguage();
// 입력 파라미터 = 신호 + 추출 방법(provenance). methods[0]=현재, 그 외=대안(이후).
const PARAMS=[
  {k:"image", en:"Image", ko:"이미지", methods:["Original photo (jpg)"], on:false},
  {k:"lat,lon", en:"Coordinates", ko:"좌표", methods:["EXIF GPS"], on:true},
  {k:"timestamp", en:"Capture time", ko:"촬영 시각", methods:["EXIF DateTimeOriginal"], on:false},
  {k:"ocr_text", en:"OCR text", ko:"OCR 텍스트", methods:["Vision VNRecognizeTextRequest","Tesseract (later)","Google Vision (later)"], on:true},
  {k:"vlm_caption", en:"VLM caption", ko:"VLM 설명", methods:["FastVLM-0.5B","LLaVA (later)"], on:false},
  {k:"nearby_candidates", en:"Nearby candidates", ko:"주변 후보", methods:["MapKit MKLocalPointsOfInterest","Google Places (later)","Kakao Local (later)"], on:true, topk:[3,5,10,"all"]},
  {k:"city,country,address", en:"Reverse geocoding", ko:"역지오코딩", methods:["Apple CLGeocoder","Google Geocoding (later)"], on:false},
];
const paramName=p=>uiLanguage==='ko'?p.ko:p.en;
const methodLabel=m=>uiLanguage==='ko'?m.replace('Original photo','원본 사진').replace(' (later)',' (추후)'):m;
function methodOf(i){const s=document.querySelector(`.prow[data-pi="${i}"] select[data-mi]`);return s?s.value:PARAMS[i].methods[0];}
function renderParams(){
  const previous=[...document.querySelectorAll('.prow')].map(row=>({
    checked:row.querySelector('input')?.checked,
    method:row.querySelector('select[data-mi]')?.value,
    topk:row.querySelector('.topk')?.value
  }));
  g('params').innerHTML='<div class="plist">'+PARAMS.map((p,i)=>{
    const method=p.methods.length>1
      ? `<select data-mi="${i}">${p.methods.map((m,j)=>`<option value="${esc(m)}"${j===0?' selected':''}>${esc(methodLabel(m))}</option>`).join('')}</select>`
      : `<span class="m">${esc(methodLabel(p.methods[0]))}</span>`;
    const topk=p.topk?`<select class="topk" data-ti="${i}" title="${bi('Number of candidates passed to the function; GT% is measured MapKit retrieval coverage.','함수에 전달할 후보 수입니다. GT%는 MapKit의 실측 검색 범위입니다.')}">${p.topk.map(nn=>{const cv=(window.COVERAGE&&window.COVERAGE[nn==='all'?'전체':nn]!=null)?` · GT ${window.COVERAGE[nn==='all'?'전체':nn]}%`:'';return `<option value="top ${nn}"${nn===5?' selected':''}>top ${nn==='all'?bi('all','전체'):nn}${cv}</option>`;}).join('')}</select>`:'';
    return `<label class="prow" data-pi="${i}"><input type="checkbox" data-k="${p.k}"${p.on?' checked':''}>
      <span class="nm">${paramName(p)}${p.warn?` <span class="warn2">${p.warn}</span>`:''}</span>
      <span class="pk">${p.k}</span><span class="mcell">${method}${topk}</span></label>`;
  }).join('')+'</div>';
  previous.forEach((state,i)=>{
    const row=g('params').querySelector(`.prow[data-pi="${i}"]`); if(!row)return;
    if(state.checked!=null)row.querySelector('input').checked=state.checked;
    if(state.method!=null&&row.querySelector('select[data-mi]'))row.querySelector('select[data-mi]').value=state.method;
    if(state.topk!=null&&row.querySelector('.topk'))row.querySelector('.topk').value=state.topk;
  });
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
    lines.push(`    ${a[0]} = ${a[1]}`.padEnd(40)+`# ${paramName(p)}`);
    const method=methodOf(i)+(tk?` · ${tk.value}`:'');
    cfg.push(`#   ${(p.k+':').padEnd(22)}${method}`);
  });
  const header=cfg.length?`# ── ${bi('run config (the harness builds each case from these selections)','실행 설정(선택한 값으로 평가 입력을 구성합니다)')} ──\n${cfg.join('\n')}\n`:'';
  g('loadsnippet').textContent=`${header}def predict(case):\n${lines.join('\n')||'    pass'}\n    # TODO: ${bi('prediction logic','예측 로직')}\n    return { "prediction": ..., "reason": ... }`;
}
function updVer(){
  const nm=g('tname').value.trim(), ex=REG[nm];
  g('verstat').innerHTML = (ex&&ex.length)
    ? bi(`Versions v${ex.join(' · v')} exist. Automatic save will create <span class="bg">v${Math.max(...ex)+1}</span>.`,`v${ex.join(' · v')}이 있습니다. 자동 저장 시 <span class="bg">v${Math.max(...ex)+1}</span>이 생성됩니다.`)
    : bi(`New run → <span class="bg">v1</span>`,`새 실행 → <span class="bg">v1</span>`);
}
function renderRuns(){
  g('runsbody').innerHTML=runsList.length ? runsList.map(r=>
    `<tr><td class="name">${esc(r.name)}</td><td><code>v${esc(r.version)}</code></td><td><code>${esc(r.lang||'—')}</code></td><td><code>${esc((r.params||[]).length+' '+bi('inputs','개'))}</code></td><td>${esc(r.scope)}</td><td>${esc(r.accuracy_pct)}%</td><td><span class="stt ok">${bi('Saved','저장됨')}</span></td></tr>`).join('') : `<tr><td colspan="7" style="color:var(--ink3);font-size:12px">${bi('No algorithm runs have been submitted.','제출된 알고리즘 실행 결과가 없습니다.')}</td></tr>`;
}
let scriptName='',scriptText='',scriptLang='python';
const LANG_BY_EXT={py:'python',c:'c',cpp:'cpp',rs:'rust',js:'node',sh:'sh'};
g('scriptfile').onchange=e=>{
  const f=e.target.files[0]; scriptName=f?f.name:''; scriptText='';
  g('filelabel').textContent=f?`📎 ${f.name} ${bi('attached','첨부됨')}`:bi('📎 Upload a script that implements predict — click or drop','📎 predict를 구현한 스크립트를 클릭하거나 끌어다 놓으세요');
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
    g('filelabel').textContent=bi('📎 baseline_nearest.py example loaded','📎 baseline_nearest.py 예시 코드를 불러왔습니다');
    document.querySelector('.filedrop').classList.add('has');
    g('tname').value='baseline-nearest'; updVer();
    hint.textContent=bi('Example ready. You can run it when a dataset is available.','예시 코드가 준비되었습니다. 데이터셋이 있으면 실행할 수 있습니다.');
  }catch(err){ hint.textContent=`${bi('Could not load example','예시 코드를 불러오지 못했습니다')}: ${err.message}`; }
};
const uploadZip=g('uploadZip');
if(uploadZip){
  uploadZip.onchange=async e=>{
    const f=e.target.files[0];
    const status=g('uploadStatus');
    if(!f) return;
    status.textContent=`${bi('Validating','검증 중')}: ${f.name}`;
    try{
      const res=await fetch('/api/validate-upload-package',{method:'POST',body:f,headers:{'Content-Type':'application/zip'}});
      const data=await res.json();
      const errs=(data.errors||[]).slice(0,5).map(x=>`${x.code||'error'}${x.row?` row ${x.row}`:''}: ${safeServerMessage(x.message,bi('Invalid upload data.','업로드 데이터가 올바르지 않습니다.'))}`).join(' / ');
      status.textContent=data.ok
        ? bi(`Valid: ${data.row_count||0} rows and ${data.image_count||0} images. EXIF, location, and provider data will be extracted during ingestion.`,`검증 완료: 행 ${data.row_count||0}개, 사진 ${data.image_count||0}개. 추가할 때 EXIF, 위치, 제공자 데이터를 추출합니다.`)
        : `${bi('Validation failed','검증 실패')}: ${errs||apiErrorMessage(data,'invalid_request')}`;
    }catch(err){ status.textContent=`${bi('Validation request failed','검증 요청 실패')}: ${err.message}`; }
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
  return raw==='all'||raw==='전체'||!raw?null:Number(raw);
}
g('runbtn').onclick=async()=>{
  if(!scriptText){ g('runhint').textContent=bi('Upload a predict() script first.','먼저 predict() 스크립트를 업로드하세요.'); return; }
  const name=(g('tname').value||'').trim()||'algorithm';
  const scope=g('rscope').value, save=g('savemode').value;
  const body={name,scope,mode:'exact',save_mode:save,lang:scriptLang,params:selectedParams(),candidate_limit:selectedCandidateLimit(),script_text:scriptText};
  g('runbtn').disabled=true; g('runhint').textContent=`${bi('Running','실행 중')}: ${name} (${scope}) …`;
  try{
    const res=await fetch('/api/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const data=await res.json();
    if(data.ok){
      const m=data.metrics||{};
      g('runhint').textContent=bi(`Completed: ${data.name} v${data.version} · accuracy ${m.accuracy_pct}% (${m.correct}/${m.n_eligible}, no prediction ${m.abstained}, errors ${m.errored})`,`완료: ${data.name} v${data.version} · 정확도 ${m.accuracy_pct}% (${m.correct}/${m.n_eligible}, 예측 없음 ${m.abstained}, 오류 ${m.errored})`);
      await loadRuns();
    }else{
      g('runhint').textContent=`${bi('Failed','실패')}: ${apiErrorMessage(data,'run_failed')}`;
    }
  }catch(err){ g('runhint').textContent=`${bi('Request failed','요청 실패')}: ${err.message}`; }
  finally{ g('runbtn').disabled=false; }
};
// live runs from /api/runs → 최근 실행 표 + 식별 정확도 막대(알고리즘별, 이름당 최신 버전)
function runKey(r){return `${r.name}__v${r.version}`}
function renderRunManager(){
 const host=g('runManagerList');if(!host)return;g('compareHint').textContent=`${comparedRunIds.size} / 4 ${bi('selected','선택')}`;
 host.innerHTML=runsList.length?runsList.map(r=>{const k=runKey(r),dups=runsList.filter(x=>x.script_sha256===r.script_sha256).length;return `<div class="runrow ${k===selectedRunId?'sel':''}" data-rkey="${esc(k)}"><div class="rt"><span>${esc(r.name)} v${r.version}</span><b>${r.accuracy_pct}%</b></div><div class="rm">${esc(r.created_at||'')} · ${esc(r.scope)} · ${esc((r.params||[]).join(', ')||bi('no additional signals','추가 신호 없음'))} · ${bi('candidates','후보')} ${r.candidate_limit==null?bi('all','전체'):r.candidate_limit}${dups>1?` · ${bi(`same code × ${dups}`,`동일 코드 ${dups}회`)}`:''}</div><label class="compare" style="margin:7px 0 0"><input type="checkbox" data-compare="${esc(k)}" ${comparedRunIds.has(k)?'checked':''}> ${bi('Include in comparison','비교에 포함')}</label></div>`}).join(''):`<div style="color:var(--ink3);font-size:12px;padding:10px">${bi('No saved runs.','저장된 실행이 없습니다.')}</div>`;
 host.querySelectorAll('[data-rkey]').forEach(el=>el.onclick=e=>{if(!e.target.matches('input'))selectRun(el.dataset.rkey)});
 host.querySelectorAll('[data-compare]').forEach(el=>el.onchange=e=>{const k=e.target.dataset.compare;if(e.target.checked&&!comparedRunIds.has(k)&&comparedRunIds.size>=4){e.target.checked=false;alert(bi('You can compare up to four runs.','실행은 최대 4개까지 비교할 수 있습니다.'));return}e.target.checked?comparedRunIds.add(k):comparedRunIds.delete(k);renderRunManager();drawCompareBars()});drawCompareBars();
}
function drawCompareBars(){const svg=g('compareBars');if(!svg)return;const rs=runsList.filter(r=>comparedRunIds.has(runKey(r))),W=580,H=210,pl=42,pr=14,pt=15,pb=42;if(!rs.length){svg.innerHTML=`<text x="290" y="105" text-anchor="middle" fill="var(--ink3)" font-size="12" font-family="var(--mono)">${bi('Select at least one run to compare.','비교할 실행을 하나 이상 선택하세요.')}</text>`;return}const y=v=>pt+(H-pt-pb)*(1-v/100),step=(W-pl-pr)/rs.length,bw=Math.min(95,step*.6);let out='';for(let v=0;v<=100;v+=25)out+=`<line x1="${pl}" y1="${y(v)}" x2="${W-pr}" y2="${y(v)}" stroke="rgba(255,255,255,.07)"/><text x="${pl-6}" y="${y(v)+4}" text-anchor="end" fill="var(--ink3)" font-size="10">${v}</text>`;rs.forEach((r,i)=>{const cx=pl+step*(i+.5),a=Number(r.accuracy_pct)||0,n=Number(r.n_eligible)||0;out+=`<rect x="${cx-bw/2}" y="${y(a)}" width="${bw}" height="${y(0)-y(a)}" rx="4" fill="var(--cyan)"/><text x="${cx}" y="${y(a)-6}" text-anchor="middle" fill="var(--ink)" font-size="11">${a}%</text>`;let x=cx-bw/2;[[r.correct,'var(--green)'],[r.abstained,'var(--orange)'],[r.errored,'var(--red)'],[Math.max(0,n-(r.correct||0)-(r.abstained||0)-(r.errored||0)),'var(--pink)']].forEach(([v,c])=>{const w=n?bw*v/n:0;out+=`<rect x="${x}" y="179" width="${w}" height="8" fill="${c}"/>`;x+=w});out+=`<text x="${cx}" y="199" text-anchor="middle" fill="var(--ink2)" font-size="10">${esc(r.name)} v${r.version}</text>`});svg.innerHTML=out}
async function selectRun(k){const r=runsList.find(x=>runKey(x)===k);if(!r)return;selectedRunId=k;runFailureDataset='all';runFailureKind='all';runFailurePage=0;renderRunManager();g('runDetail').textContent=bi('Loading run details…','실행 상세를 불러오는 중…');try{const d=await apiJSON(`/api/runs?name=${encodeURIComponent(r.name)}&version=${r.version}`,'run-detail');selectedRun=d.run;renderRunDetail()}catch(e){g('runDetail').textContent=bi('Could not load run details.','실행 상세를 불러오지 못했습니다.')}}
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
  const failRows=shown.map(c=>{const kind=c.error?'error':(c.prediction?'wrong':'abstained'),ctx=c.context||{};const title=ctx.input_place_name||c.gt||c.photo||'case';const location=[ctx.category,ctx.city,ctx.country].filter(Boolean).join(' · ');const prediction=c.error?`${label.error}: ${safeServerMessage(c.error,label.error)}`:(c.prediction||label.abstained);const ocr=ctx.ocr_text?`<span class="failreason">OCR: ${esc(ctx.ocr_text)}</span>`:'';const coords=(ctx.lat&&ctx.lon)?`<span class="failmeta">${esc(ctx.lat)}, ${esc(ctx.lon)}</span>`:'';const image=c.photo_url?`<img class="failthumb" src="${esc(c.photo_url)}" alt="" loading="lazy">`:'<span class="failthumb"></span>';return `<div class="failrow">${image}<span><span class="failtitle">${esc(title)}</span><span class="failmeta">${esc(location||c.dataset||'—')}</span><span class="failreason">GT: ${esc(c.gt||'—')} → ${esc(prediction)}</span>${ocr}${coords}<span class="failmeta">${esc(c.photo||'')}</span></span><span class="oc ${kind==='error'?'retrieval':kind==='wrong'?'selection':'other'}">${esc(kindLabel[kind])}</span></div>`}).join('')||`<div>${label.noFailures}</div>`;
  g('runDetail').innerHTML=`<div style="display:flex;justify-content:space-between;gap:10px"><b style="color:var(--ink)">${esc(r.name)} v${r.version}</b><button class="btn danger" id="deleteRun">${label.del}</button></div><div class="dl"><b>${label.created}</b><span>${esc(r.created_at||'')}</span><b>${label.config}</b><span>${esc(r.scope)} · ${esc(r.mode)} · ${label.candidates} ${r.candidate_limit==null?label.all:r.candidate_limit}</span><b>${label.inputs}</b><span>${esc((r.params||[]).join(', ')||label.none)}</span><b>${label.identity}</b><span title="${esc(hash||(L?'스크립트 텍스트가 없어 코드 식별값을 만들 수 없습니다.':'No script text was available to derive an identity.'))}">${esc(hashText)} <button class="btn" type="button" id="viewRunCode">${L?'코드 보기':'View code'}</button></span></div><div><b style="color:var(--ink)">${m.accuracy_pct||0}% · ${m.correct||0}/${n}</b> ${label.correct}</div><div class="outcomes">${part(m.correct||0,'var(--green)')}${part(m.abstained||0,'var(--orange)')}${part(m.errored||0,'var(--red)')}${part(wrong,'var(--pink)')}</div><div style="font:11px var(--mono);color:var(--ink3)">${label.correct} ${m.correct||0} · ${label.abstained} ${m.abstained||0} · ${label.errors} ${m.errored||0} · ${label.wrong} ${wrong}</div><div class="casefail"><b style="color:var(--ink3)">${label.failures} · ${allFails.length} ${label.total}, ${filtered.length} ${label.matching}</b><div class="detail-filters"><select id="failureDataset"><option value="all">${label.allDatasets}</option>${datasets.map(x=>`<option value="${esc(x)}" ${x===runFailureDataset?'selected':''}>${esc(x)}</option>`).join('')}</select><select id="failureKind"><option value="all">${label.allOutcomes}</option>${kinds.map(x=>`<option value="${x}" ${x===runFailureKind?'selected':''}>${esc(kindLabel[x]||x)}</option>`).join('')}</select></div>${failRows}<div class="pager"><button id="failurePrev" ${runFailurePage===0?'disabled':''}>${label.previous}</button><span>${filtered.length?`${runFailurePage+1} / ${pages}`:'0 / 0'}</span><button id="failureNext" ${runFailurePage>=pages-1?'disabled':''}>${label.next}</button></div></div>`;
  g('deleteRun').onclick=()=>deleteSelectedRun(r);
  g('viewRunCode').onclick=showRunCode;
  g('failureDataset').onchange=e=>{runFailureDataset=e.target.value;runFailurePage=0;renderRunDetail()};
  g('failureKind').onchange=e=>{runFailureKind=e.target.value;runFailurePage=0;renderRunDetail()};
  g('failurePrev').onclick=()=>{runFailurePage--;renderRunDetail()};
  g('failureNext').onclick=()=>{runFailurePage++;renderRunDetail()};
}
async function deleteSelectedRun(r){if(!confirm(bi(`Permanently delete "${r.name}" v${r.version}?\n\nThis removes the saved run and its case results.`,`"${r.name}" v${r.version}을 영구 삭제할까요?\n\n저장된 실행과 사례 결과가 삭제됩니다.`)))return;try{const res=await fetch(`/api/runs?name=${encodeURIComponent(r.name)}&version=${r.version}`,{method:'DELETE'}),d=await res.json();if(!res.ok||!d.ok)throw Error(apiErrorMessage(d,res.status===404?'not_found':'request_failed'));comparedRunIds.delete(runKey(r));selectedRunId=null;selectedRun=null;g('runDetail').textContent=bi('Run deleted.','실행이 삭제되었습니다.');await loadRuns()}catch(e){alert(`${bi('Could not delete run','실행을 삭제하지 못했습니다')}: ${e.message}`)}}

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
let _dsData=null, _jobsData=null, _jobTimer=null, _watchJob=null, _pollBusy=false;
const _shownWarnings=new Set();
// step -> ① 신호 파이프라인 row label to annotate while running
const STEP_PIPELINE={ocr:'Vision OCR', mapkit_nearby:'MapKit 베이스라인', gt_mapkit:'MapKit 정규명(GT)'};
const jobStatusLabel=status=>tl('jobStatus',status,status);
const API_ERROR_MESSAGES={
  en:{busy:'Another data job is already running.',disabled:'This operation is disabled.',not_implemented:'This step is not implemented.',unknown_step:'Unknown extraction step.',not_found:'The requested item was not found.',invalid_request:'The request is invalid.',invalid_provider:'The selected provider is invalid.',upload_save_failed:'The upload could not be saved.',run_failed:'The algorithm run failed.',internal_error:'The server could not complete the request.',request_failed:'The request could not be completed.'},
  ko:{busy:'다른 데이터 작업이 이미 실행 중입니다.',disabled:'이 작업은 현재 사용할 수 없습니다.',not_implemented:'아직 지원하지 않는 단계입니다.',unknown_step:'알 수 없는 추출 단계입니다.',not_found:'요청한 항목을 찾을 수 없습니다.',invalid_request:'요청이 올바르지 않습니다.',invalid_provider:'선택한 제공자가 올바르지 않습니다.',upload_save_failed:'업로드 파일을 저장하지 못했습니다.',run_failed:'알고리즘 실행에 실패했습니다.',internal_error:'서버에서 요청을 처리하지 못했습니다.',request_failed:'요청을 완료하지 못했습니다.'}
};
function apiErrorMessage(payload,fallbackCode='request_failed'){
  const data=payload&&typeof payload==='object'?payload:{};
  const code=data.error_code||fallbackCode;
  const localized=(API_ERROR_MESSAGES[uiLanguage]||API_ERROR_MESSAGES.en)[code];
  if(localized)return localized;
  const raw=String(data.error||'').trim();
  if(raw&&((uiLanguage==='en'&&!hasKorean(raw))||(uiLanguage==='ko'&&hasKorean(raw))))return raw;
  return API_ERROR_MESSAGES[uiLanguage][fallbackCode]||API_ERROR_MESSAGES[uiLanguage].request_failed;
}
const hasKorean=value=>/[가-힣]/.test(String(value||''));
const safeServerMessage=(value,fallback='')=>{
  const raw=String(value||'').trim();
  if(!raw)return fallback;
  return uiLanguage==='en'&&hasKorean(raw)?fallback:raw;
};
const humanizeCode=value=>String(value||'').replace(/[_-]+/g,' ').replace(/\b\w/g,c=>c.toUpperCase());
const stepLabel=(step,fallback='')=>{
  const known=tl('step',step);
  if(known) return known;
  if(uiLanguage==='en'&&hasKorean(fallback)) return humanizeCode(step)||'Unknown step';
  return fallback||humanizeCode(step)||'';
};
const signalStatusLabel=status=>tl('signalStatus',status,uiLanguage==='en'&&hasKorean(status)?'Unavailable':(status||''));
const SIGNAL_RESULT_LABELS_EN={'텍스트 검출':'Text detected','후보 검출':'Candidates detected','좌표 보유':'Coordinates available','촬영 시각 보유':'Capture time available'};
const signalResultLabel=label=>uiLanguage==='en'?(SIGNAL_RESULT_LABELS_EN[label]||'Result detected'):(label||'결과 검출');

const warningMessage=w=>{
  if(uiLanguage==='ko') return w.message||'';
  if(w.code==='exif_gps_missing') return `${w.count}/${w.targets} source photos have no EXIF GPS coordinates. Coordinate-based steps have no input.`;
  if(w.code==='exif_timestamp_missing') return `${w.count}/${w.targets} source photos have no EXIF capture time.`;
  return hasKorean(w.message)?'The job completed with a warning.':(w.message||'The job completed with a warning.');
};

async function loadDatasets(data=null){
  let d=data; try{ d=d||await apiJSON('/api/datasets','datasets'); }catch(e){ return; }
  _dsData=d;
  const sig=d.signals_meta||{};
  gid('dsTable').innerHTML=(d.datasets||[]).map(ds=>{
    const bars=Object.values(ds.signals||{}).map(s=>{
      const dis=s.status&&s.status!=='ok';
      const metric=(label,count,pct,kind='')=>`<div class="signal-metric ${kind}${pct===0?' empty':''}" title="${esc(label)}: ${count}/${ds.count} (${pct}%)"><div class="signal-metric-head"><span class="signal-metric-label">${esc(label)}</span><span class="signal-metric-value"><span class="signal-metric-count">${count} / ${ds.count}</span><strong class="signal-metric-pct">${pct}%</strong></span></div><div class="signal-track" aria-hidden="true"><div class="signal-fill" style="width:${pct}%"></div></div></div>`;
      if(s.coverage_metrics?.length&&!dis){
        const metrics=s.coverage_metrics.map(item=>metric(signalResultLabel(item.label),item.count,item.pct,'detected')).join('');
        return `<div class="signal-status"><div class="signal-title">${esc(stepLabel(s.step,s.label))}</div><div class="signal-metrics">${metrics}</div></div>`;
      }
      if(s.processed!=null&&!dis){
        return `<div class="signal-status"><div class="signal-title">${esc(stepLabel(s.step,s.label))}</div><div class="signal-metrics">${metric(bi('Processed','처리 완료'),s.processed,s.processed_pct,'processed')}${metric(signalResultLabel(s.result_label),s.fill,s.pct,'detected')}</div></div>`;
      }
      const label=stepLabel(s.step,s.label), status=signalStatusLabel(s.status);
      if(s.label_breakdown&&!dis){
        const breakdown=s.label_breakdown;
        const items=(breakdown.items||[]).map(item=>({...item,label:tl('mapkitGt',item.key,item.key)}));
        const segments=items.map(item=>`<span class="gt-segment ${esc(item.key)}" style="width:${item.pct}%" title="${esc(item.label)}: ${item.count}/${breakdown.total} (${item.pct}%)"></span>`).join('');
        const legend=items.map(item=>`<span class="gt-label-item ${esc(item.key)}"><i></i><span>${esc(item.label)}</span><b>${item.pct}%</b><small>${item.count} / ${breakdown.total}</small></span>`).join('');
        const excluded=breakdown.excluded||{}, excludedText=[];
        if(excluded.kor)excludedText.push(`KOR ${excluded.kor}`);
        if(excluded.empty)excludedText.push(`${bi('empty','빈 값')} ${excluded.empty}`);
        const note=excludedText.length?`<span class="gt-excluded">${bi('Outside 3 labels','3개 라벨 외')} · ${excludedText.join(' · ')}</span>`:'';
        return `<div class="signal-status"><div class="signal-title">${esc(label)}</div><div class="gt-breakdown"><div class="gt-stacked-track" aria-label="${esc(label)}">${segments}</div><div class="gt-label-legend">${legend}</div>${note}</div></div>`;
      }
      return `<div class="signal-status"><div class="signal-title">${esc(label)}</div>${dis?`<div class="signal-unavailable">${esc(status)}</div>`:`<div class="signal-metrics single">${metric(bi('Result available','결과 보유'),s.fill,s.pct,'detected')}</div>`}</div>`;
    }).join('');
    return `<tr><td class="nm3">${esc(ds.key)}${ds.known?'':` <span style="color:var(--orange)" title="${bi('Missing config source','설정 출처 없음')}">⚠</span>`}</td><td class="m3">${ds.count}</td><td><div class="dataset-signals">${bars}</div></td><td><button class="btn" data-del="${esc(ds.key)}" style="border-color:rgba(255,107,92,.45);background:rgba(255,107,92,.10);color:#ffb3aa">${bi('Delete','삭제')}</button></td></tr>`;
  }).join('')||`<tr><td colspan="4" style="color:var(--ink3)">${bi('No datasets.','데이터셋이 없습니다.')}</td></tr>`;
  gid('rerunDataset').innerHTML=(d.datasets||[]).map(ds=>`<option value="${esc(ds.key)}">${esc(ds.key)}</option>`).join('');
  gid('rerunStep').innerHTML=Object.entries(sig).map(([name,s])=>{
    const dis=s.status&&s.status!=='ok';
    return `<option value="${esc(s.step||name)}"${dis?' disabled':''}>${esc(stepLabel(s.step||name,s.label))}${dis?' · '+esc(signalStatusLabel(s.status)):''}</option>`;
  }).join('');
  const hasData=(d.datasets||[]).length>0;
  gid('rerunDataset').disabled=!hasData;
  gid('rerunStep').disabled=!hasData;
  gid('rerunBtn').disabled=!hasData;
  g('runbtn').disabled=!hasData;
  if(!hasData){
    gid('rerunHint').textContent=bi('Add a dataset first.','먼저 데이터셋을 추가하세요.');
    g('runhint').textContent=bi('No dataset is available. You can still load the example code.','등록된 데이터셋이 없어 실행할 수 없습니다. 예시 코드는 미리 불러올 수 있습니다.');
  }else if(g('runhint').textContent===bi('No dataset is available. You can still load the example code.','등록된 데이터셋이 없어 실행할 수 없습니다. 예시 코드는 미리 불러올 수 있습니다.')){
    g('runhint').textContent='';
  }
  gid('dsTable').querySelectorAll('button[data-del]').forEach(b=>b.onclick=()=>deleteDataset(b.dataset.del));
}

async function deleteDataset(key){
  const ds=(_dsData&&_dsData.datasets||[]).find(x=>x.key===key)||{count:'?'};
  const fullCleanup=ds.source_type==='upload';
  const detail=fullCleanup
    ? bi('CSV rows, uploaded images, and the upload configuration will be removed.','CSV 행, 업로드한 사진, 업로드 설정을 모두 삭제합니다.')
    : bi('Only CSV rows will be removed and backed up. Shared image files and configuration will remain.','CSV 행만 삭제하고 백업합니다. 공유될 수 있는 사진과 설정은 유지합니다.');
  if(!confirm(bi(`Delete dataset "${key}" (${ds.count} rows)?\n\n${detail}\n\nThis cannot be undone.`,`데이터셋 "${key}"(행 ${ds.count}개)을 삭제할까요?\n\n${detail}\n\n이 작업은 되돌릴 수 없습니다.`))) return;
  try{
    const res=await fetch(`/api/jobs?step=delete_dataset&dataset=${encodeURIComponent(key)}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({delete_photos:fullCleanup,remove_config_source:fullCleanup})});
    const d=await res.json();
    if(!d.ok){ alert(`${bi('Delete failed','삭제 실패')}: ${apiErrorMessage(d,res.status===409?'busy':'request_failed')}`); return; }
    watchJob(d.job_id);
  }catch(e){ alert(`${bi('Delete request failed','삭제 요청 실패')}: ${e.message}`); }
}

async function doRerun(){
  const step=gid('rerunStep').value, dataset=gid('rerunDataset').value;
  const onlyEmpty=gid('rerunOnlyEmpty').checked?1:0, hint=gid('rerunHint'); hint.textContent='';
  if(!step){ hint.textContent=bi('Select a step.','단계를 선택하세요.'); return; }
  try{
    const res=await fetch(`/api/jobs?step=${encodeURIComponent(step)}&dataset=${encodeURIComponent(dataset)}&only_empty=${onlyEmpty}`,{method:'POST'});
    const d=await res.json();
    if(!d.ok){ hint.textContent=apiErrorMessage(d,res.status===409?'busy':(res.status===501?'not_implemented':'request_failed')); if(res.status===409) pollJobs(); return; }
    hint.textContent=`${bi('Started','시작됨')} (${d.job_id})`; watchJob(d.job_id);
  }catch(e){ hint.textContent=`${bi('Request failed','요청 실패')}: ${e.message}`; }
}

function watchJob(id){ _watchJob=id; startJobPolling(); }

function fmtResult(r){
  if(!r) return '';
  if(r.step==='delete_dataset') return bi(`Deleted ${r.removed_rows} rows · backup created`,`행 ${r.removed_rows}개 삭제 · 백업 생성`);
  const p=[]; if(r.processed!=null)p.push(`${bi('Processed','처리')} ${r.processed}/${r.targets!=null?r.targets:'?'}`); if(r.detected!=null)p.push(`${bi('Detected','검출')} ${r.detected}/${r.targets!=null?r.targets:'?'}`); else if(r.filled!=null)p.push(`${bi('Filled','채움')} ${r.filled}/${r.targets!=null?r.targets:'?'}`);
  if(r.counts)p.push(Object.entries(r.counts).map(([k,v])=>`${k}:${v}`).join(' '));
  return p.join(' · ')||(r.ok?'ok':'');
}

async function pollJobs(data=null){
  let d=data; try{ d=d||await apiJSON('/api/jobs','jobs'); }catch(e){ return null; }
  _jobsData=d;
  const active=(d.jobs||[]).find(j=>j.job_id===d.active);
  const ab=gid('jobActive');
  if(ab){ if(active){ const pr=active.progress, subs=pr&&pr.substeps; const bars=subs?`<div style="display:grid;gap:5px;margin-top:8px">${Object.entries(subs).map(([name,x])=>{const pct=x.total?Math.round(100*x.done/x.total):0;const reason=x.retry_reason?safeServerMessage(x.retry_reason,bi('temporary error','일시적 오류')):'';const retry=x.retries?` · ${bi('retries','재시도')} ${x.retries}${reason?': '+esc(reason):''}`:'';return `<div><span style="display:inline-block;width:150px">${esc(stepLabel(name,name))} · ${esc(x.step?stepLabel(x.step):jobStatusLabel(x.status||''))}</span><span style="display:inline-block;width:150px;height:6px;background:#333c66;vertical-align:middle"><i style="display:block;width:${pct}%;height:100%;background:var(--orange)"></i></span> ${x.done}/${x.total}${retry}</div>`}).join('')}</div>`:''; ab.innerHTML=`<span style="color:var(--orange)">● ${bi('Running','실행 중')}</span> ${esc(stepLabel(active.step))}${active.params&&active.params.dataset?' · '+esc(active.params.dataset):''} · ${active.elapsed_s||0}s${pr?` · ${pr.done}/${pr.total}`:''}${bars}`; } else ab.textContent=bi('No active job.','실행 중인 작업이 없습니다.'); }
  const jl=gid('jobList');
  if(jl){
    const jobs=(d.jobs||[]).slice().sort((a,b)=>(b.started||0)-(a.started||0)).slice(0,8);
    jl.innerHTML=jobs.map(j=>{
      const sc=j.status==='done'?'stt ok':(j.status==='error'?'stt':'stt run2');
      const est=j.status==='error'?'background:rgba(255,107,92,.15);color:var(--red)':'';
      return `<tr><td class="name">${esc(stepLabel(j.step))}</td><td>${esc((j.params&&j.params.dataset)||bi('All','전체'))}${j.params&&j.params.only_empty?` · ${bi('unprocessed rows','미처리 행')}`:''}</td><td><span class="${sc}" style="${est}">${esc(jobStatusLabel(j.status))}</span></td><td class="m3">${j.elapsed_s!=null?j.elapsed_s+'s':''}</td><td style="font-family:var(--mono);font-size:11px;color:var(--ink2)">${esc(fmtResult(j.result)||(j.error?safeServerMessage(j.error,API_ERROR_MESSAGES[uiLanguage].internal_error):''))}</td></tr>`;
    }).join('');
  }
  if(_watchJob){ const wj=(d.jobs||[]).find(j=>j.job_id===_watchJob); const lg=gid('jobLog'); if(wj&&lg){ const lines=wj.log_tail||[];const localized=uiLanguage==='en'?lines.filter(line=>!hasKorean(line)):lines;lg.style.display='block';lg.textContent=localized.join('\n')||(lines.length?bi('No localized log entries.','표시할 로그가 없습니다.'):''); } }
  (d.jobs||[]).forEach(j=>(j.warnings||[]).forEach(w=>{
    const key=`${j.job_id}:${w.code}`; if(_shownWarnings.has(key)) return;
    _shownWarnings.add(key);
    if(w.code==='exif_gps_missing' || w.code==='exif_timestamp_missing'){
      const message=warningMessage(w), st=gid('uploadStatus'); if(st) st.textContent=`⚠ ${message}`;
      alert(`${bi('Upload warning','업로드 경고')}\n\n${message}`);
    }
  }));
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
  const pr=job.progress, badge=` · ${bi('running','실행 중')}${pr?` ${pr.done}/${pr.total}`:''} ${job.elapsed_s||0}s`;
  document.querySelectorAll('#pipelinebars .pl').forEach(pl=>{
    const l=pl.querySelector('.lbl');
    if(l&&l.textContent.trim()===(uiLanguage==='en'?(PIPELINE_LABELS_EN[lbl]||lbl):lbl)){ const st=pl.querySelector('.st'); if(st){ st.textContent=bi('In progress','진행 중')+badge; st.style.color='var(--orange)'; } const seg=pl.querySelector('.seg'); if(seg) seg.style.background='var(--orange)'; }
  });
}

const _rerunBtn=gid('rerunBtn'); if(_rerunBtn) _rerunBtn.addEventListener('click',doRerun);
const _ingestZip=gid('ingestZip');
if(_ingestZip) _ingestZip.onchange=async e=>{
  const f=e.target.files[0]; if(!f) return; const st=gid('uploadStatus');
  st.textContent=bi(`Adding dataset: uploading ${f.name}…`,`데이터셋 추가 중: ${f.name} 업로드…`);
  try{
    const res=await fetch('/api/ingest',{method:'POST',body:f,headers:{'Content-Type':'application/zip'}});
    const d=await res.json();
    if(!d.ok){ st.textContent=`${bi('Could not add dataset','데이터셋 추가 실패')}: ${apiErrorMessage(d,res.status===409?'busy':'request_failed')}`; if(res.status===409) pollJobs(); }
    else { st.textContent=bi(`Ingestion started (${d.job_id}). Track progress under Jobs and Overview.`,`데이터 추가를 시작했습니다(${d.job_id}). 작업과 개요에서 진행 상황을 확인하세요.`); watchJob(d.job_id); }
  }catch(err){ st.textContent=`${bi('Add request failed','추가 요청 실패')}: ${err.message}`; }
  e.target.value='';
};
loadDatasets();
pollJobs().then(d=>{ if(d&&d.active) startJobPolling(); });
function loadAll(){ apiFailures.clear(); loadOverviewSummary(); loadRowStruct(); render(); loadCases(); loadRuns(); loadDatasets(); pollJobs(); }
