// Runs before the page is drawn (loaded in <head> without defer), so the saved
// theme applies without a flash of the other one.
(() => {
  let saved = null;
  try { saved = localStorage.getItem("parchment-theme"); } catch (e) { /* storage blocked */ }
  const dark = window.matchMedia && matchMedia("(prefers-color-scheme: dark)").matches;
  document.documentElement.dataset.theme = saved || (dark ? "dark" : "light");
})();
