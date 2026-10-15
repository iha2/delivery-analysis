(function () {
  "use strict";
  const DA = window.DA;

  function load(name, extra) { return DA.api("/api/metrics/" + name + DA.query(extra)); }

  function throughput(cards) {
    const body = DA.card(cards, "Throughput by week", "Pull requests merged per week (issues done appear when Jira is connected)");
    load("prs_merged_weekly").then(function (r) {
      if (DA.showResult(body, r)) { return; }
      DA.charts.bars(DA.canvas(body), r.rows.map(function (w) { return w.week; }), r.rows.map(function (w) { return w.value; }), "PRs merged");
      DA.table(body, ["Week starting", "PRs merged"], r.rows.map(function (w) { return [w.week, w.value]; }));
      DA.notes(body, r.notes);
    }).catch(function (e) { DA.message(body, e.message, "error"); });
  }

  function timeToMerge(cards) {
    const body = DA.card(cards, "Time to merge", "From opening a pull request to merging it");
    load("time_to_merge").then(function (r) {
      if (DA.showResult(body, r)) { return; }
      body.appendChild(DA.el("div", { class: "stats" }, [
        DA.el("div", { class: "stat" }, [DA.el("strong", { text: DA.fmt(r.team.value, "hours") }), DA.el("span", { text: "median" })]),
        DA.el("div", { class: "stat" }, [DA.el("strong", { text: DA.fmt(r.team.p85, "hours") }), DA.el("span", { text: "85th percentile" })]),
        DA.el("div", { class: "stat" }, [DA.el("strong", { text: String(r.team.sample) }), DA.el("span", { text: "pull requests" })]),
      ]));
      DA.notes(body, r.notes);
    }).catch(function (e) { DA.message(body, e.message, "error"); });
  }

  function breakdown(cards) {
    const body = DA.card(cards, "PR lead time breakdown", "Median hours in each stage");
    load("lead_time_breakdown").then(function (r) {
      if (DA.showResult(body, r)) { return; }
      DA.charts.hbars(DA.canvas(body), r.rows.map(function (p) { return p.part; }), r.rows.map(function (p) { return p.median_hours || 0; }), "Median hours");
      DA.table(body, ["Stage", "Median", "Pull requests"], r.rows.map(function (p) { return [p.part, DA.fmt(p.median_hours, "hours"), p.count]; }));
      DA.notes(body, r.notes);
    }).catch(function (e) { DA.message(body, e.message, "error"); });
  }

  function perPerson(cards, name, title, subtitle) {
    const body = DA.card(cards, title, subtitle);
    load(name).then(function (r) {
      if (DA.showResult(body, r)) { return; }
      const rows = r.rows.filter(function (x) { return x.value; }).slice(0, 10);
      if (!rows.length) { DA.message(body, "Nothing open right now."); return; }
      DA.charts.hbars(DA.canvas(body), rows.map(function (x) { return x.name; }), rows.map(function (x) { return x.value; }), title);
      DA.table(body, ["Person", title], rows.map(function (x) { return [x.name, DA.fmt(x.value, r.unit)]; }));
      DA.notes(body, r.notes);
    }).catch(function (e) { DA.message(body, e.message, "error"); });
  }

  function waiting(container) {
    DA.api("/api/metrics").then(function (data) {
      container.textContent = "";
      data.metrics.filter(function (m) { return m.status === "waiting"; }).forEach(function (m) {
        const body = DA.card(container, m.label, m.description);
        DA.message(body, "Needs " + m.missing.join(" and ") + ".");
      });
    }).catch(function (e) { DA.message(container, e.message, "error"); });
  }

  DA.page(function render() {
    const cards = document.getElementById("cards");
    cards.textContent = "";
    throughput(cards);
    timeToMerge(cards);
    breakdown(cards);
    perPerson(cards, "review_load", "Review load", "Open pull requests waiting on each reviewer, right now");
    perPerson(cards, "work_in_progress", "Work in progress", "Open pull requests by author, right now");
    waiting(document.getElementById("waiting"));
  });
})();
