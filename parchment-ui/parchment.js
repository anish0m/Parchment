
(() => {
  const root = document.documentElement;
  const saved = localStorage.getItem("parchment-theme");
  root.dataset.theme = saved || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");

  const syncIcons = () => document.querySelectorAll("[data-theme-icon]").forEach(el => {
    el.textContent = root.dataset.theme === "dark" ? "☀" : "☾";
  });
  document.addEventListener("click", e => {
    const theme = e.target.closest("[data-theme-toggle]");
    if(theme){
      root.dataset.theme = root.dataset.theme === "dark" ? "light" : "dark";
      localStorage.setItem("parchment-theme", root.dataset.theme);
      syncIcons();
    }
    const user = e.target.closest("[data-user-button]");
    if(user){
      e.stopPropagation();
      document.querySelector("[data-user-menu]")?.classList.toggle("open");
    } else if(!e.target.closest("[data-user-menu]")){
      document.querySelector("[data-user-menu]")?.classList.remove("open");
    }
    const modalOpen = e.target.closest("[data-open-modal]");
    if(modalOpen) openModal(modalOpen.dataset.openModal);
    const modalClose = e.target.closest("[data-close-modal]");
    if(modalClose) closeModal(modalClose.dataset.closeModal);
  });

  window.openModal = id => { const m=document.getElementById(id); if(!m) return; m.classList.add("open"); document.body.classList.add("modal-open"); };
  window.closeModal = id => { const m=document.getElementById(id); if(!m) return; m.classList.remove("open"); if(!document.querySelector(".modal-backdrop.open")) document.body.classList.remove("modal-open"); };
  document.addEventListener("click", e => {
    if(e.target.classList.contains("modal-backdrop")) closeModal(e.target.id);
  });
  syncIcons();

  window.logout = () => {
    localStorage.removeItem("parchment-session");
    window.location.href = "landing-page.html";
  };
})();
