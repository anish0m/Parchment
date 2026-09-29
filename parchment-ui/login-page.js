document.querySelector('.auth-form')?.addEventListener('submit', e => { e.preventDefault(); localStorage.setItem('parchment-session','demo'); window.location.href='courses-page.html'; });
