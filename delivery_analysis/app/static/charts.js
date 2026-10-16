/* Thin Chart.js wrappers: rounded bars, recessive grid, tooltips on, a legend only for two or more series. */
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

  function series(canvas, labels, datasets, opts) {
    const options = opts || {};
    const type = options.type === "line" ? "line" : "bar";
    const grid = token("--grid");
    const ink = token("--text-secondary");
    canvas.setAttribute("aria-label", datasets.map(function (d) { return d.label; }).join(", "));
    const built = datasets.map(function (d, i) {
      const colour = token("--series-" + Math.min(i + 1, 3));
      if (type === "line") {
        return { label: d.label, data: d.data, borderColor: colour, backgroundColor: colour, borderWidth: 2, pointRadius: 2, tension: 0.2, spanGaps: false };
      }
      return { label: d.label, data: d.data, backgroundColor: colour, borderRadius: 4, borderSkipped: "start", maxBarThickness: 28 };
    });
    return draw(canvas, {
      type: type,
      data: { labels: labels, datasets: built },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: datasets.length > 1, labels: { color: ink } }, tooltip: { enabled: true } },
        scales: {
          x: { stacked: !!options.stacked, grid: { color: "transparent" }, ticks: { color: ink } },
          y: { stacked: !!options.stacked, beginAtZero: true, grid: { color: grid }, ticks: { color: ink } },
        },
      },
    });
  }

  function scatter(canvas, points, opts) {
    const axes = opts || {};
    const grid = token("--grid");
    const ink = token("--text-secondary");
    canvas.setAttribute("aria-label", (axes.y || "y") + " against " + (axes.x || "x"));
    return draw(canvas, {
      type: "scatter",
      data: { datasets: [{
        label: (axes.y || "y") + " against " + (axes.x || "x"),
        data: points.map(function (p) { return { x: p.x, y: p.y }; }),
        backgroundColor: token("--series-1"), pointRadius: 5, pointHoverRadius: 7,
      }] },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: { enabled: true, callbacks: { label: function (item) {
            const p = points[item.dataIndex];
            return p.label + ": " + p.x + " / " + p.y;
          } } },
        },
        scales: {
          x: { beginAtZero: true, title: { display: true, text: axes.x || "", color: ink }, grid: { color: grid }, ticks: { color: ink } },
          y: { beginAtZero: true, title: { display: true, text: axes.y || "", color: ink }, grid: { color: grid }, ticks: { color: ink } },
        },
      },
    });
  }

  DA.charts = {
    bars: function (canvas, labels, values, label) { return bars(canvas, labels, values, label, false); },
    hbars: function (canvas, labels, values, label) { return bars(canvas, labels, values, label, true); },
    series: function (canvas, labels, datasets, opts) { return series(canvas, labels, datasets, opts); },
    scatter: function (canvas, points, opts) { return scatter(canvas, points, opts); },
  };
})();
