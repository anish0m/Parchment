const show=document.querySelector('#show-answer'), ans=document.querySelector('#study-answer'), ratings=document.querySelector('#rating-row');
show?.addEventListener('click',()=>{ans.classList.add('visible');ratings.classList.add('visible');show.style.display='none';});
