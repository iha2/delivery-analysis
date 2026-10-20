(function () {
  "use strict";
  const DA = window.DA;
  const STATS = [["prs_merged", "PRs merged"], ["reviews_given", "Reviews given"], ["reviews_assigned", "Reviews assigned"],
                 ["review_response_rate", "Response rate"], ["time_to_merge", "Median time to merge"], ["commits", "Commits"],
                 ["story_points_done", "Story points done"], ["issues_done", "Issues done"], ["cycle_time", "Median cycle time"],
                 ["cost_spent", "Claude cost"], ["story_points_per_dollar", "Points per dollar"]];

  function list(container, headers, rows) {
    container.textContent = "";
    if (!rows.length) { DA.message(container, "None in this window."); return; }
    const head = DA.el("tr", {}, headers.map(function (h) { return DA.el("th", { text: h }); }));
    container.appendChild(DA.el("table", {}, [DA.el("thead", {}, [head]), DA.el("tbody", {}, rows.map(function (r) {
      return DA.el("tr", {}, r.map(function (c) { return DA.el("td", { text: c === null || c === undefined ? "–" : String(c) }); }));
    }))]));
  }

  function tiles(container, pairs, id) {
    container.textContent = "";
    pairs.forEach(function (pair) {
      const tile = DA.el("div", { class: "stat" }, [DA.el("strong", { text: "…" }), DA.el("span", { text: pair[1] })]);
      container.appendChild(tile);
      DA.api("/api/metrics/" + pair[0] + DA.query({ include_inactive: "true" })).then(function (r) {
        const row = (r.rows || []).find(function (x) { return x.person_id === id; });
        tile.firstChild.textContent = r.status === "ok" && row ? DA.fmt(row.value, r.unit) : "–";
      }).catch(function () { tile.firstChild.textContent = "–"; });
    });
  }


  const charts = {};

  function token(name) { return getComputedStyle(document.body).getPropertyValue(name).trim(); }

  function hasValues(values) { return values.some(function (v) { return v !== null && v !== undefined; }); }

  function empty(key, text) {
    if (charts[key]) { charts[key].destroy(); delete charts[key]; }
    const note = document.getElementById("empty-" + key);
    note.textContent = text;
    note.classList.toggle("hidden", !text);
    document.getElementById("chart-" + key).parentNode.classList.toggle("hidden", !!text);
    return !!text;
  }

  function draw(key, config) {
    if (empty(key, "")) { return; }
    if (typeof window.Chart === "undefined") { empty(key, "Charts are unavailable because Chart.js did not load."); return; }
    charts[key] = new window.Chart(document.getElementById("chart-" + key), config);
  }

  function axes(stacked, horizontal) {
    const grid = token("--grid");
    const ink = token("--text-secondary");
    return {
      x: { stacked: stacked, beginAtZero: true, grid: { color: horizontal ? grid : "transparent" }, ticks: { color: ink } },
      y: { stacked: stacked, beginAtZero: true, grid: { color: horizontal ? "transparent" : grid }, ticks: { color: ink } },
    };
  }

  function medianLine(values) {
    return { type: "line", label: "Team median", data: values, borderColor: token("--text-muted"), backgroundColor: token("--text-muted"),
             borderDash: [6, 4], borderWidth: 2, pointRadius: 0, tension: 0.2, spanGaps: false, order: 0 };
  }

  function options(stacked, horizontal) {
    return { responsive: true, maintainAspectRatio: false, indexAxis: horizontal ? "y" : "x",
             plugins: { legend: { display: true, labels: { color: token("--text-secondary") } }, tooltip: { enabled: true } },
             scales: axes(stacked, horizontal) };
  }

  function lineChart(d, key, label, noData) {
    if (!hasValues(d.series[key])) { empty(key, noData || "No data yet"); return; }
    const colour = token("--series-1");
    draw(key, { type: "line", data: { labels: d.dates, datasets: [
      { label: label, data: d.series[key], borderColor: colour, backgroundColor: colour, borderWidth: 2, pointRadius: 2, tension: 0.2, spanGaps: false },
      medianLine(d.team_median[key]),
    ] }, options: options(false, false) });
  }

  function impactChart(d) {
    if (!hasValues(d.series.delivery) && !hasValues(d.series.participation)) { empty("impact", "No data yet"); return; }
    draw("impact", { type: "bar", data: { labels: d.dates, datasets: [
      { label: "Delivery", data: d.series.delivery, backgroundColor: token("--series-1"), borderRadius: 3, stack: "impact" },
      { label: "Participation", data: d.series.participation, backgroundColor: token("--series-3"), borderRadius: 3, stack: "impact" },
      medianLine(d.team_median.impact),
    ] }, options: options(true, false) });
  }

  function splitChart(d) {
    const last = d.dates.length - 1;
    if (last < 0 || (d.series.delivery[last] === null && d.series.participation[last] === null)) { empty("split", "No data yet"); return; }
    draw("split", { type: "bar", data: { labels: ["Delivery", "Participation"], datasets: [
      { label: "This person", data: [d.series.delivery[last], d.series.participation[last]], backgroundColor: token("--series-1"), borderRadius: 3 },
      { label: "Team median", data: [d.team_median.delivery[last], d.team_median.participation[last]], backgroundColor: token("--series-2"), borderRadius: 3 },
    ] }, options: options(false, true) });
  }

  function showSeries(d) {
    impactChart(d);
    lineChart(d, "impact_per_dollar", "Impact per dollar", "Waiting for Claude usage data");
    splitChart(d);
    lineChart(d, "delivery", "Delivery points");
    lineChart(d, "delivery_speed", "Delivery speed (hours)");
    lineChart(d, "durability", "Durability");
    lineChart(d, "participation", "Participation points");
    lineChart(d, "prs_reviewed", "PRs reviewed");
    lineChart(d, "review_value", "Review value");
    const notes = document.getElementById("series-notes");
    notes.textContent = "";
    DA.notes(notes, d.notes);
  }

  function loadSeries() {
    const s = DA.state();
    const params = new URLSearchParams({ window_days: document.getElementById("person-window").value });
    if (s.team) { params.set("team", s.team); }
    DA.api("/api/person/" + encodeURIComponent(s.id) + "/series?" + params.toString()).then(showSeries).catch(function (e) {
      const notes = document.getElementById("series-notes");
      DA.message(notes, e.message, "error");
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.getElementById("person-window").addEventListener("change", function () { if (DA.state().id) { loadSeries(); } });
  });

  function day(iso) { return iso ? iso.slice(0, 10) : "–"; }

  DA.page(function render() {
    const s = DA.state();
    if (!s.id) { DA.message(document.getElementById("series-notes"), "Open a person from Rankings."); return; }
    DA.api("/api/people/" + encodeURIComponent(s.id) + DA.query()).then(function (d) {
      document.getElementById("person-name").textContent = d.person.name;
      document.getElementById("person-identities").textContent =
        [d.person.accounts.join(", "), d.person.emails.join(", "), d.window.label].filter(Boolean).join(" · ");
      const commits = document.getElementById("person-commits");
      commits.textContent = "";
      DA.charts.bars(DA.canvas(commits), d.commits_weekly.map(function (w) { return w.week; }), d.commits_weekly.map(function (w) { return w.value; }), "Commits");
      DA.table(commits, ["Week starting", "Commits"], d.commits_weekly.map(function (w) { return [w.week, w.value]; }));
      const issuesCard = document.getElementById("person-issues-card");
      if (d.issues_done) {
        issuesCard.classList.remove("hidden");
        list(document.getElementById("person-issues"), ["Issue", "Type", "Story points", "Credit", "Credited via", "Resolved"],
          d.issues_done.map(function (i) { return [i.key, i.type, i.points, Math.round(i.share * 100) + "%", i.basis, day(i.resolved_at)]; }));
      } else {
        issuesCard.classList.add("hidden");
      }
      list(document.getElementById("person-pending"), ["#", "Title", "Repository", "Opened"],
        d.reviews_pending.map(function (p) { return [p.number, p.title, p.repository, day(p.created_at)]; }));
      list(document.getElementById("person-prs"), ["#", "Title", "Repository", "State", "Opened", "Merged"],
        d.pull_requests.map(function (p) { return [p.number, p.title, p.repository, p.state, day(p.created_at), day(p.merged_at)]; }));
      list(document.getElementById("person-reviews"), ["#", "Title", "Repository", "Kind", "When"],
        d.reviews_given.map(function (r) { return [r.number, r.title, r.repository, r.type, day(r.occurred_at)]; }));
    }).catch(function (e) { DA.message(document.getElementById("person-prs"), e.message, "error"); });

    const tickets = document.getElementById("person-tickets");
    DA.api("/api/tickets" + DA.query({ person: s.id })).then(function (t) {
      list(tickets, ["Ticket", "Type", "Points", "Claude cost", "Points per $", "Confidence", "PRs", "Hours to merge"],
        t.tickets.map(function (x) {
          return [x.key, x.type, x.points, DA.fmt(x.cost_usd, "usd"), DA.fmt(x.points_per_usd, "points_per_usd"),
                  x.confidence, x.pull_requests, DA.fmt(x.hours_to_merge, "hours")];
        }));
      if (t.cost_weekly && t.cost_weekly.some(function (w) { return w.cost_usd; })) {
        DA.charts.bars(DA.canvas(tickets), t.cost_weekly.map(function (w) { return w.week; }),
          t.cost_weekly.map(function (w) { return w.cost_usd; }), "Claude cost (USD)");
      }
      DA.notes(tickets, t.notes);
    }).catch(function (e) { DA.message(tickets, e.message, "error"); });

    loadSeries();
    tiles(document.getElementById("person-stats"), STATS, s.id);
  });
})();
