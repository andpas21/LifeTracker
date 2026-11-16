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

  // Anteprima dell'icona nei selettori (data-icon-preview="<id del select>").
  document.querySelectorAll("[data-icon-preview]").forEach(function (preview) {
    var select = document.getElementById(preview.getAttribute("data-icon-preview"));
    if (!select) return;
    select.addEventListener("change", function () {
      preview.innerHTML = '<i class="bi bi-' + (select.value || "dash") + '"></i>';
    });
  });

  var csrfToken = (document.querySelector('meta[name="csrf-token"]') || {}).content;

  // Registrazione rapida: invio senza ricaricare la pagina + notifica con link ai dettagli.
  var performerSelect = document.querySelector("[data-quick-performer]");
  if (performerSelect) {
    performerSelect.addEventListener("change", function () {
      document.querySelectorAll("[data-performer-input]").forEach(function (input) { input.value = performerSelect.value; });
    });
  }
  document.querySelectorAll("[data-quick-form]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      if (!window.fetch) return; // senza fetch: invio classico
      event.preventDefault();
      var button = form.querySelector("button");
      button.disabled = true;
      fetch(form.action, {
        method: "POST",
        body: new FormData(form),
        headers: { "Accept": "application/json", "X-CSRFToken": csrfToken },
        credentials: "same-origin",
      }).then(function (response) {
        return response.json().then(function (data) { return { ok: response.ok, data: data }; });
      }).then(function (result) {
        var toastEl = document.getElementById("ltQuickToast");
        toastEl.querySelector("[data-toast-text]").textContent = result.data.message;
        var link = toastEl.querySelector("[data-toast-link]");
        if (result.ok) {
          link.href = result.data.details_url;
          link.classList.remove("d-none");
          button.classList.add("lt-done");
          setTimeout(function () { button.classList.remove("lt-done"); }, 1200);
          if (navigator.vibrate) navigator.vibrate(30);
        } else {
          link.classList.add("d-none");
        }
        window.bootstrap.Toast.getOrCreateInstance(toastEl, { delay: 4000 }).show();
      }).catch(function () {
        form.submit(); // fallback: invio classico
      }).finally(function () { button.disabled = false; });
    });
  });

  // Form completo: cambiando attività si ricarica il form con i suoi indicatori.
  document.querySelectorAll("[data-reload-activity]").forEach(function (select) {
    select.addEventListener("change", function () {
      var url = new URL(select.getAttribute("data-reload-activity"), window.location.origin);
      url.searchParams.set("attivita", select.value);
      var current = new URL(window.location.href);
      if (current.searchParams.get("data")) url.searchParams.set("data", current.searchParams.get("data"));
      window.location.href = url.toString();
    });
  });

  // Filtri dashboard: le date "dal/al" servono solo con il periodo personalizzato.
  document.querySelectorAll("[data-period-select]").forEach(function (select) {
    var toggle = function () {
      document.querySelectorAll("[data-custom-range]").forEach(function (el) {
        el.classList.toggle("d-none", select.value !== "custom");
        el.querySelector("input").disabled = select.value !== "custom";
      });
    };
    select.addEventListener("change", toggle);
    toggle();
  });

  // Form obiettivi: mostra solo i campi pertinenti.
  document.querySelectorAll("[data-goal-form]").forEach(function (form) {
    var update = function () {
      var scope = form.querySelector('input[name="scope"]:checked');
      var personal = !scope || scope.value === "personal";
      var target = form.querySelector('[name="target_type"]').value;
      form.querySelector("[data-goal-personal]").classList.toggle("d-none", !personal);
      form.querySelector("[data-goal-metric]").classList.toggle("d-none", target !== "metric");
      form.querySelector("[data-goal-scope-fields]").classList.toggle("d-none", target === "metric");
    };
    form.addEventListener("change", update);
    update();
  });

  // Select che inviano subito il form (filtri calendario).
  document.querySelectorAll("[data-autosubmit]").forEach(function (el) {
    el.addEventListener("change", function () { el.form.submit(); });
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
