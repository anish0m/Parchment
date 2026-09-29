const procBar=document.querySelector('#proc-bar'), procPct=document.querySelector('#proc-percent'), procStatus=document.querySelector('#proc-status');
let processing=Number(localStorage.getItem('parchment-processing')||58);
const statuses=['Extracting text…','Cleaning extracted text…','Clustering concepts…','Generating flashcards…','Checking card quality…'];
function renderProc(){if(procBar)procBar.style.width=processing+'%';if(procPct)procPct.textContent=processing+'%';if(procStatus)procStatus.textContent=statuses[Math.min(Math.floor(processing/21),4)];}
renderProc();
setInterval(()=>{if(processing<96){processing=Math.min(96,processing+1);localStorage.setItem('parchment-processing',processing);renderProc();}},1800);
document.querySelector('[data-start-processing]')?.addEventListener('click',()=>{closeModal('material-modal');openModal('processing-modal');processing=Math.max(processing,3);localStorage.setItem('parchment-processing',processing);renderProc();});
document.querySelector('#pdf-file')?.addEventListener('change',e=>{const f=e.target.files?.[0];document.querySelector('#file-name').textContent=f?f.name:'No file selected.';});


// Material source tabs: only one input method is active at a time.
document.querySelectorAll('[data-material-tab]').forEach(tab => {
  tab.addEventListener('click', () => {
    const target = tab.dataset.materialTab;
    document.querySelectorAll('[data-material-tab]').forEach(t => {
      const active = t === tab; t.classList.toggle('active', active); t.setAttribute('aria-selected', active);
    });
    document.querySelectorAll('[data-material-panel]').forEach(panel => panel.classList.toggle('active', panel.dataset.materialPanel === target));
  });
});
