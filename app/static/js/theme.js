/* Applica il tema prima del rendering della pagina (evita il "lampo" chiaro in modalità scura).
   Preferenza salvata sul server in data-theme-pref: auto | light | dark. */
(function () {
  var root = document.documentElement;
  var media = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
  function apply() {
    var pref = root.getAttribute("data-theme-pref") || "auto";
    var dark = pref === "dark" || (pref === "auto" && media && media.matches);
    root.setAttribute("data-bs-theme", dark ? "dark" : "light");
  }
  apply();
  if (media && media.addEventListener) media.addEventListener("change", apply);
})();
