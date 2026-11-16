/* LifeTracker — grafici Chart.js.
   Ogni <canvas data-chart="ID"> legge la specifica JSON da <script type="application/json" id="ID">
   (preparata dal server in stats_service.chart) e la converte in configurazione Chart.js.
   Stile: segni sottili, griglia discreta, testo con i colori del tema, legenda per più serie. */
(function () {
  "use strict";
  if (!window.Chart) return;

  var css = getComputedStyle(document.documentElement);
  function v(name, fallback) { return (css.getPropertyValue(name) || "").trim() || fallback; }
  var dark = document.documentElement.getAttribute("data-bs-theme") === "dark";
  var textColor = v("--bs-body-color", dark ? "#e5e7eb" : "#1f2937");
  var mutedColor = v("--bs-secondary-color", dark ? "#9ca3af" : "#6b7280");
  var gridColor = dark ? "rgba(255,255,255,.07)" : "rgba(15,23,42,.06)";
  var surface = v("--lt-surface", dark ? "#171a23" : "#ffffff");

  Chart.defaults.color = mutedColor;
  Chart.defaults.font.family = v("--bs-body-font-family", "system-ui");
  Chart.defaults.font.size = 12;

  var nf = new Intl.NumberFormat("it-IT", { maximumFractionDigits: 1 });

  function hexToRgba(hex, alpha) {
    var h = (hex || "#4f46e5").replace("#", "");
    var n = parseInt(h.length === 3 ? h.split("").map(function (c) { return c + c; }).join("") : h, 16);
    return "rgba(" + ((n >> 16) & 255) + "," + ((n >> 8) & 255) + "," + (n & 255) + "," + alpha + ")";
  }

  function formatValue(value, spec) {
    if (value === null || value === undefined) return "—";
    if (spec.duration) {
      var minutes = Math.round(value * 60);
      return Math.floor(minutes / 60) + ":" + String(minutes % 60).padStart(2, "0") + " h";
    }
    return nf.format(value) + (spec.unit ? " " + spec.unit : "");
  }

  function build(spec) {
    var type = spec.type;
    var multi = spec.datasets.length > 1;
    var datasets = spec.datasets.map(function (ds) {
      var color = ds.color || "#4f46e5";
      var base = { label: ds.label, data: ds.data };
      if (type === "line") {
        return Object.assign(base, {
          borderColor: color, backgroundColor: hexToRgba(color, spec.stacked ? 0.55 : 0.14),
          borderWidth: 2, pointRadius: 0, pointHoverRadius: 5, pointHitRadius: 12, tension: 0.15, cubicInterpolationMode: "monotone",
          fill: spec.fill ? (spec.stacked ? "stack" : "origin") : false, spanGaps: true,
          borderDash: ds.dashed ? [6, 4] : undefined,
        });
      }
      if (type === "bar") {
        var colors = ds.colors || color;
        return Object.assign(base, {
          backgroundColor: colors, borderColor: surface, borderWidth: 0, borderRadius: 4,
          borderSkipped: "start", maxBarThickness: 32, categoryPercentage: 0.7, barPercentage: 0.9,
        });
      }
      if (type === "doughnut") {
        return Object.assign(base, { backgroundColor: ds.colors, borderColor: surface, borderWidth: 2, hoverOffset: 4 });
      }
      if (type === "radar") {
        return Object.assign(base, {
          borderColor: color, backgroundColor: hexToRgba(color, 0.12), borderWidth: 2,
          pointRadius: 3, pointBackgroundColor: color,
        });
      }
      return base;
    });

    var showLegend = multi || type === "doughnut";
    var options = {
      responsive: true, maintainAspectRatio: false,
      interaction: type === "line" ? { mode: "index", intersect: false } : { mode: "nearest", intersect: true },
      plugins: {
        legend: { display: showLegend, position: "bottom", labels: { color: textColor, usePointStyle: true, boxWidth: 8, padding: 14 } },
        tooltip: {
          backgroundColor: dark ? "#0b0d12" : "#111827", padding: 10, cornerRadius: 8, displayColors: true,
          callbacks: {
            label: function (ctx) {
              var raw = type === "doughnut" || type === "radar" ? ctx.raw : (spec.horizontal ? ctx.parsed.x : ctx.parsed.y);
              var label = type === "doughnut" ? ctx.label : (ctx.dataset.label || "");
              return " " + label + ": " + formatValue(raw, spec);
            },
          },
        },
      },
    };
    if (type === "line" || type === "bar") {
      var valueAxis = {
        beginAtZero: true, stacked: !!spec.stacked, grid: { color: gridColor }, border: { display: false },
        ticks: { color: mutedColor, maxTicksLimit: 6, callback: function (value) { return formatValue(value, spec).replace(" h", ""); } },
      };
      var catAxis = { stacked: !!spec.stacked, grid: { display: false }, border: { color: gridColor },
                      ticks: { color: mutedColor, maxRotation: 0, autoSkip: true, autoSkipPadding: 12 } };
      options.indexAxis = spec.horizontal ? "y" : "x";
      options.scales = spec.horizontal ? { x: valueAxis, y: catAxis } : { x: catAxis, y: valueAxis };
    }
    if (type === "radar") {
      options.scales = { r: { beginAtZero: true, grid: { color: gridColor }, angleLines: { color: gridColor },
                              pointLabels: { color: textColor }, ticks: { display: false } } };
    }
    if (type === "doughnut") options.cutout = "62%";
    return { type: type, data: { labels: spec.labels, datasets: datasets }, options: options };
  }

  document.querySelectorAll("canvas[data-chart]").forEach(function (canvas) {
    var source = document.getElementById(canvas.getAttribute("data-chart"));
    if (!source) return;
    var spec = JSON.parse(source.textContent);
    var hasData = spec.datasets.some(function (ds) { return ds.data.some(function (x) { return x; }); });
    if (!hasData) {
      canvas.parentElement.classList.add("lt-chart-empty");
      return;
    }
    new Chart(canvas, build(spec));
  });
})();
