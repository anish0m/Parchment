const form=document.querySelector('.auth-form'); const p=document.querySelector('#pw'); const p2=document.querySelector('#pw2'); const help=document.querySelector('#pw-help');
function check(){if(!p||!p2||!help)return; help.textContent=p2.value&&p.value!==p2.value?'Passwords do not match.':''; help.style.color='var(--danger)';}
p?.addEventListener('input',check);p2?.addEventListener('input',check);
form?.addEventListener('submit',e=>{e.preventDefault();if(p.value!==p2.value)return;localStorage.setItem('parchment-session','demo');window.location.href='courses-page.html';});
