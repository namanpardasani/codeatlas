// Runs before first paint (loaded synchronously from index.html; a file, not inline, so the CSP needs no 'unsafe-inline').
// Theme = saved choice, else the OS setting.
(function () {
  var t = null;
  try { t = localStorage.getItem("codeatlas.theme"); } catch (e) {}
  if (t !== "light" && t !== "dark") t = window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  document.documentElement.dataset.theme = t;
})();
