/* Thin Chart.js wrappers: one series, rounded bars, recessive grid, tooltips on. */
(function () {
  "use strict";
  const DA = (window.DA = window.DA || {});
  const live = new Map();

  function token(name) { return getComputedStyle(document.body).getPropertyValue(name).trim(); }

  function draw(canvas, config) {
    if (live.has(canvas)) { live.get(canvas).destroy(); }
    if (typeof window.Chart === "undefined") {
      canvas.parentNode.replaceWith(DA.el("p", { class: "note", text: "Charts are unavailable because Chart.js did not load; use the table below." }));
      return null;
    }
    const chart = new window.Chart(canvas, config);
    live.set(canvas, chart);
    return chart;
  }

  function bars(canvas, labels, values, label, horizontal) {
    const grid = token("--grid");
    const ink = token("--text-secondary");
    canvas.setAttribute("aria-label", label);
    return draw(canvas, {
      type: "bar",
      data: { labels: labels, datasets: [{
        label: label, data: values, backgroundColor: token("--series-1"),
        borderRadius: 4, borderSkipped: "start", maxBarThickness: 28,
      }] },
      options: {
        responsive: true, maintainAspectRatio: false, indexAxis: horizontal ? "y" : "x",
        plugins: { legend: { display: false }, tooltip: { enabled: true } },
        scales: {
          x: { beginAtZero: true, grid: { color: horizontal ? grid : "transparent" }, ticks: { color: ink } },
          y: { beginAtZero: true, grid: { color: horizontal ? "transparent" : grid }, ticks: { color: ink } },
        },
      },
    });
  }

  DA.charts = {
    bars: function (canvas, labels, values, label) { return bars(canvas, labels, values, label, false); },
    hbars: function (canvas, labels, values, label) { return bars(canvas, labels, values, label, true); },
  };
})();
