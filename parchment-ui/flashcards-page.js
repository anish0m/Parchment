const source=document.querySelector('#source');
source?.addEventListener('change',()=>{if(source.value==='processing')openModal('processing-modal');});
const procBar=document.querySelector('#proc-bar'), procPct=document.querySelector('#proc-percent'), procStatus=document.querySelector('#proc-status');
let processing=Number(localStorage.getItem('parchment-processing')||58);
function renderProc(){if(procBar)procBar.style.width=processing+'%';if(procPct)procPct.textContent=processing+'%';if(procStatus)procStatus.textContent=processing<70?'Clustering concepts…':processing<85?'Generating flashcards…':'Checking card quality…';}
renderProc();setInterval(()=>{if(processing<96){processing++;localStorage.setItem('parchment-processing',processing);renderProc();}},1800);
