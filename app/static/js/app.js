/* LifeTracker — comportamenti comuni a tutte le pagine. */
(function () {
  "use strict";

  // Conferma prima di inviare i form con attributo data-confirm (eliminazioni, rimozioni...).
  document.addEventListener("submit", function (event) {
    var form = event.target;
    var message = form.getAttribute && form.getAttribute("data-confirm");
    if (message && !window.confirm(message)) {
      event.preventDefault();
    }
  });

  // Pulsanti "Copia": data-copy="#idElemento" copia il valore/testo dell'elemento.
  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-copy]");
    if (!button) return;
    var target = document.querySelector(button.getAttribute("data-copy"));
    if (!target) return;
    var text = target.value !== undefined ? target.value : target.textContent.trim();
    var done = function () {
      var original = button.innerHTML;
      button.innerHTML = '<i class="bi bi-check2"></i> Copiato';
      setTimeout(function () { button.innerHTML = original; }, 1500);
    };
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(done);
    } else {
      // Fallback per HTTP non sicuro (es. accesso via IP in rete locale)
      var area = document.createElement("textarea");
      area.value = text;
      document.body.appendChild(area);
      area.select();
      try { document.execCommand("copy"); done(); } finally { document.body.removeChild(area); }
    }
  });

  // Pulsanti "Condividi" (Web Share API, disponibile soprattutto su smartphone).
  document.querySelectorAll("[data-share-url]").forEach(function (button) {
    if (!navigator.share) return;
    button.classList.remove("d-none");
    button.addEventListener("click", function () {
      navigator.share({
        title: "LifeTracker",
        text: button.getAttribute("data-share-text") || "",
        url: button.getAttribute("data-share-url"),
      }).catch(function () { /* condivisione annullata */ });
    });
  });

  // Gli avvisi di successo/informazione si chiudono da soli.
  document.querySelectorAll(".lt-flashes .alert-success, .lt-flashes .alert-info").forEach(function (alert) {
    setTimeout(function () {
      if (window.bootstrap) window.bootstrap.Alert.getOrCreateInstance(alert).close();
    }, 5000);
  });

  // Registrazione del service worker (PWA installabile + pagina offline).
  if ("serviceWorker" in navigator && window.isSecureContext) {
    window.addEventListener("load", function () {
      navigator.serviceWorker.register("/sw.js").catch(function (err) {
        console.warn("Service worker non registrato:", err);
      });
    });
  }
})();
