(function () {
  "use strict";
  const DA = window.DA;
  // Metrics that have a card (or feed one): the "Coming with new sources" list skips them.
  const ON_CARDS = ["story_points_weekly", "story_points_done", "issues_done", "points_by_type", "cycle_time_weekly",
    "cycle_time_summary", "prs_linked_weekly", "prs_with_issue_link", "story_points_per_dollar", "ask_generate_ratio",
    "story_points_per_dollar_weekly", "story_points_per_dollar_all_in", "unattributed_cost_share", "cost_by_purpose_weekly",
    "issues_done_weekly", "prs_merged_weekly", "time_to_merge", "lead_time_breakdown", "review_load", "work_in_progress"];

  function load(name, extra) { return DA.api("/api/metrics/" + name + DA.query(extra)); }
  function fail(body) { return function (e) { DA.message(body, e.message, "error"); }; }
  function sum(rows, key) { return rows.reduce(function (total, row) { return total + (row[key] || 0); }, 0); }
  function weeks(rows) { return rows.map(function (row) { return row.week; }); }
  function tile(content, label) {
    return DA.el("div", { class: "stat" }, [DA.el("strong", {}, [content]), DA.el("span", { text: label })]);
  }
  function basis(body, text) { body.appendChild(DA.el("p", { class: "note", text: text })); }

  function impact(cards) {
    const body = DA.card(cards, "Impact delivered", "Story points of completed issues, credited to the authors of their linked pull requests (the assignee when none is linked)");
    Promise.all([load("story_points_weekly"), load("story_points_done")]).then(function (all) {
      const weekly = all[0], done = all[1];
      if (DA.showResult(body, weekly)) { return; }
      // Totals and the trend come from the server (story_points_done's team total); the weekly
      // sums are only a fallback when that metric is unavailable.
      const hasTeam = done.status === "ok" && !!done.team;
      const total = hasTeam && done.team.value !== null ? done.team.value : sum(weekly.rows, "value");
      const completed = sum(weekly.rows, "issues");
      const without = sum(weekly.rows, "unpointed");
      const trend = hasTeam ? done.team.trend : null;
      const previous = hasTeam ? done.team.previous : null;
      body.appendChild(DA.el("div", { class: "stats" }, [
        tile(DA.fmt(total, "points"), "story points done"),
        tile(DA.trend(trend, "higher"), previous === null || previous === undefined ? "vs previous window" : "vs previous window (" + DA.fmt(previous, "points") + " points)"),
        tile(DA.fmt(completed, "count"), "completed issues"),
        tile(DA.fmt(without, "count"), "without points"),
      ]));
      DA.charts.bars(DA.canvas(body), weeks(weekly.rows), weekly.rows.map(function (w) { return w.value; }), "Story points");
      DA.table(body, ["Week starting", "Story points", "Issues"], weekly.rows.map(function (w) { return [w.week, DA.fmt(w.value, "points"), w.issues]; }));
      basis(body, "Based on " + (completed - without) + " completed issues with story points.");
      DA.notes(body, weekly.notes);
      if (trend === null || trend === undefined) { DA.notes(body, (done.notes || []).filter(function (n) { return n.indexOf("trend") !== -1; })); }
    }).catch(fail(body));
  }

  function whereItWent(cards) {
    const body = DA.card(cards, "Where it went", "Story points by issue type");
    load("points_by_type").then(function (r) {
      if (DA.showResult(body, r)) { return; }
      if (!r.rows.length) { DA.message(body, "No completed issues with story points in this window."); DA.notes(body, r.notes); return; }
      DA.charts.hbars(DA.canvas(body), r.rows.map(function (p) { return p.part; }), r.rows.map(function (p) { return p.value; }), "Story points");
      DA.table(body, ["Issue type", "Story points", "Issues"], r.rows.map(function (p) { return [p.part, DA.fmt(p.value, "points"), p.count]; }));
      basis(body, "Based on " + sum(r.rows, "count") + " completed issues with story points.");
      DA.notes(body, r.notes);
    }).catch(fail(body));
  }

  function howFast(cards) {
    const body = DA.card(cards, "How fast", "Hours from first In Progress to COMPLETED, and to the first merged linked pull request, counting each issue once");
    Promise.all([load("cycle_time_weekly"), load("cycle_time_summary")]).then(function (all) {
      const r = all[0], summary = all[1];
      if (DA.showResult(body, r)) { return; }
      const count = sum(r.rows, "count");
      if (!count) { DA.message(body, "No completed issues with a start time in this window."); DA.notes(body, r.notes); return; }
      if (summary.status === "ok") {
        body.appendChild(DA.el("div", { class: "stats" }, summary.rows.map(function (p) {
          return tile(DA.fmt(p.median, "hours"), "median " + p.part.toLowerCase() + " (85th percentile " + DA.fmt(p.p85, "hours") + ", " + p.count + " issues)");
        })));
      }
      DA.charts.series(DA.canvas(body), weeks(r.rows), [
        { label: "Median to COMPLETED", data: r.rows.map(function (w) { return w.median; }) },
        { label: "85th percentile to COMPLETED", data: r.rows.map(function (w) { return w.p85; }) },
        { label: "Median to first PR merge", data: r.rows.map(function (w) { return w.pr_median; }) },
      ], { type: "line" });
      DA.table(body, ["Week starting", "Median", "85th percentile", "Issues", "Median to first PR merge", "Issues with a merged PR"],
        r.rows.map(function (w) { return [w.week, DA.fmt(w.median, "hours"), DA.fmt(w.p85, "hours"), w.count, DA.fmt(w.pr_median, "hours"), w.pr_count]; }));
      basis(body, "Based on " + count + " completed issues with a start time.");
      DA.notes(body, r.notes);
    }).catch(fail(body));
  }

  function evidence(cards) {
    const body = DA.card(cards, "Evidence", "Merged pull requests per week, split by whether an issue key links them");
    Promise.all([load("prs_linked_weekly"), load("prs_with_issue_link")]).then(function (all) {
      const weekly = all[0], rate = all[1];
      if (DA.showResult(body, weekly)) { return; }
      if (rate.status === "ok" && rate.team) {
        body.appendChild(DA.el("div", { class: "stats" }, [
          tile(DA.fmt(rate.team.value, "ratio"), "of merged pull requests link to an issue"),
          tile(String(rate.team.sample), "merged pull requests"),
        ]));
      }
      DA.charts.series(DA.canvas(body), weeks(weekly.rows), [
        { label: "Linked to an issue", data: weekly.rows.map(function (w) { return w.linked; }) },
        { label: "No issue key", data: weekly.rows.map(function (w) { return w.unlinked; }) },
      ], { type: "bar", stacked: true });
      DA.table(body, ["Week starting", "Linked", "No issue key"], weekly.rows.map(function (w) { return [w.week, w.linked, w.unlinked]; }));
      if (rate.status === "ok") {
        const people = rate.rows.filter(function (x) { return x.sample > 0; });
        if (people.length) {
          DA.table(body, ["Person", "Link rate", "Merged pull requests"],
            people.map(function (x) { return [x.name, DA.fmt(x.value, "ratio"), x.sample]; }));
        }
      }
      DA.notes(body, weekly.notes);
    }).catch(fail(body));
  }

  function unique(list) {
    return list.filter(function (item, index) { return item && list.indexOf(item) === index; });
  }

  function impactPerToken(cards) {
    const body = DA.card(cards, "Impact per token", "Story points per dollar of attributed Claude cost (cost proxy), by completion week");
    Promise.all([load("story_points_per_dollar_weekly"), load("story_points_per_dollar"),
                 load("story_points_per_dollar_all_in"), load("unattributed_cost_share")]).then(function (rs) {
      const weekly = rs[0];
      if (DA.showResult(body, weekly)) { return; }
      const team = function (r) { return r.team ? r.team.value : null; };
      body.appendChild(DA.el("div", { class: "stats" }, [
        tile(DA.fmt(team(rs[1]), "points_per_usd"), "attributed"),
        tile(DA.fmt(team(rs[2]), "points_per_usd"), "all-in"),
        tile(DA.fmt(team(rs[3]), "ratio"), "unattributed cost share"),
      ]));
      DA.charts.series(DA.canvas(body), weeks(weekly.rows),
        [{ label: "Points per dollar", data: weekly.rows.map(function (w) { return w.value; }) }], { type: "line" });
      DA.table(body, ["Week starting", "Tickets", "Points", "Attributed cost", "Points per dollar"],
        weekly.rows.filter(function (w) { return w.tickets; }).map(function (w) {
          return [w.week, w.tickets, DA.fmt(w.points), DA.fmt(w.cost_usd, "usd"), DA.fmt(w.value, "points_per_usd")];
        }));
      DA.notes(body, unique((weekly.notes || []).concat(rs[1].notes || [])));
    }).catch(fail(body));
  }

  function costVsPoints(cards) {
    const body = DA.card(cards, "Cost and impact by person", "Attributed Claude cost against credited story points, tickets completed in the window");
    load("story_points_per_dollar").then(function (r) {
      if (DA.showResult(body, r)) { return; }
      const people = r.rows.filter(function (x) { return x.person_id && x.denominator !== undefined; });
      if (!people.length) { DA.message(body, "No completed tickets with Claude cost in this window."); return; }
      DA.charts.scatter(DA.canvas(body), people.map(function (x) {
        return { x: x.denominator, y: x.numerator,
                 label: x.name + (x.ranked ? "" : " (unranked)") + (x.confidence ? ", " + x.confidence + " confidence" : "") };
      }), { x: "Attributed Claude cost (USD)", y: "Credited story points" });
      if (r.team && r.team.value !== null) {
        basis(body, "Team: " + DA.fmt(r.team.value, "points_per_usd") +
          " points per dollar. People above that slope deliver more points per dollar than the team; compare people with their own trend first.");
      }
      DA.table(body, ["Person", "Cost", "Points", "Points per dollar", "Confidence"], people.map(function (x) {
        return [x.name, DA.fmt(x.denominator, "usd"), DA.fmt(x.numerator), DA.fmt(x.value, "points_per_usd"), x.confidence || "–"];
      }));
      DA.notes(body, r.notes);
    }).catch(fail(body));
  }

  function askVsGenerate(cards) {
    const body = DA.card(cards, "Ask vs generate", "Context only, not a score: Claude cost by purpose per week, a coarse proxy (v1) with low confidence");
    Promise.all([load("cost_by_purpose_weekly"), load("ask_generate_ratio")]).then(function (rs) {
      const weekly = rs[0], ratio = rs[1];
      if (DA.showResult(body, weekly)) { return; }
      const pick = function (name) { return weekly.rows.map(function (w) { return w[name]; }); };
      DA.charts.series(DA.canvas(body), weeks(weekly.rows), [
        { label: "Ask", data: pick("ask") },
        { label: "Generate", data: pick("generate") },
        { label: "Unclassified", data: pick("unclassified") },
      ], { type: "bar", stacked: true });
      DA.table(body, ["Week starting", "Ask", "Generate", "Unclassified"], weekly.rows.map(function (w) {
        return [w.week, DA.fmt(w.ask, "usd"), DA.fmt(w.generate, "usd"), DA.fmt(w.unclassified, "usd")];
      }));
      if (ratio.status === "ok") {
        const rows = ratio.rows.filter(function (x) { return x.person_id && x.value !== null; })
          .sort(function (a, b) { return a.name.localeCompare(b.name); });
        if (rows.length) {
          DA.charts.hbars(DA.canvas(body), rows.map(function (x) { return x.name; }), rows.map(function (x) { return x.value; }),
            "Ask to generate (context, not a score)");
          DA.table(body, ["Person", "Ask to generate"], rows.map(function (x) { return [x.name, DA.fmt(x.value, ratio.unit)]; }));
        }
      }
      DA.notes(body, unique((weekly.notes || []).concat(ratio.notes || [])));
    }).catch(fail(body));
  }

  function throughput(cards) {
    const body = DA.card(cards, "Throughput by week", "Pull requests merged per week, and issues done when Jira is connected");
    load("prs_merged_weekly").then(function (r) {
      if (DA.showResult(body, r)) { return; }
      DA.charts.bars(DA.canvas(body), weeks(r.rows), r.rows.map(function (w) { return w.value; }), "PRs merged");
      DA.table(body, ["Week starting", "PRs merged"], r.rows.map(function (w) { return [w.week, w.value]; }));
      DA.notes(body, r.notes);
      return load("issues_done_weekly").then(function (issues) {
        if (issues.status !== "ok") { basis(body, "Issues done appear here when Jira is connected."); return; }
        body.appendChild(DA.el("p", { class: "note", text: "Issues done per week" }));
        DA.charts.bars(DA.canvas(body, "small"), weeks(issues.rows), issues.rows.map(function (w) { return w.value; }), "Issues done");
        DA.table(body, ["Week starting", "Issues done"], issues.rows.map(function (w) { return [w.week, w.value]; }));
        DA.notes(body, issues.notes);
      });
    }).catch(fail(body));
  }

  function timeToMerge(cards) {
    const body = DA.card(cards, "Time to merge", "From opening a pull request to merging it");
    load("time_to_merge").then(function (r) {
      if (DA.showResult(body, r)) { return; }
      body.appendChild(DA.el("div", { class: "stats" }, [
        tile(DA.fmt(r.team.value, "hours"), "median"),
        tile(DA.fmt(r.team.p85, "hours"), "85th percentile"),
        tile(String(r.team.sample), "pull requests"),
      ]));
      DA.notes(body, r.notes);
    }).catch(fail(body));
  }

  function breakdown(cards) {
    const body = DA.card(cards, "PR lead time breakdown", "Median hours in each stage");
    load("lead_time_breakdown").then(function (r) {
      if (DA.showResult(body, r)) { return; }
      DA.charts.hbars(DA.canvas(body), r.rows.map(function (p) { return p.part; }), r.rows.map(function (p) { return p.median_hours || 0; }), "Median hours");
      DA.table(body, ["Stage", "Median", "Pull requests"], r.rows.map(function (p) { return [p.part, DA.fmt(p.median_hours, "hours"), p.count]; }));
      DA.notes(body, r.notes);
    }).catch(fail(body));
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
    }).catch(fail(body));
  }

  function waiting(container) {
    DA.api("/api/metrics").then(function (data) {
      container.textContent = "";
      data.metrics.filter(function (m) { return m.status === "waiting" && ON_CARDS.indexOf(m.name) === -1; }).forEach(function (m) {
        const body = DA.card(container, m.label, m.description);
        DA.message(body, "Needs " + m.missing.map(DA.sourceLabel).join(" and ") + ".");
      });
    }).catch(function (e) { DA.message(container, e.message, "error"); });
  }

  DA.page(function render() {
    const cards = document.getElementById("cards");
    cards.textContent = "";
    impact(cards);
    whereItWent(cards);
    howFast(cards);
    evidence(cards);
    impactPerToken(cards);
    costVsPoints(cards);
    askVsGenerate(cards);
    throughput(cards);
    timeToMerge(cards);
    breakdown(cards);
    perPerson(cards, "review_load", "Review load", "Open pull requests waiting on each reviewer, right now");
    perPerson(cards, "work_in_progress", "Work in progress", "Open pull requests by author, right now");
    waiting(document.getElementById("waiting"));
  });
})();
