(function () {
  "use strict";
  const DA = window.DA;
  const STATS = [["prs_merged", "PRs merged"], ["reviews_given", "Reviews given"], ["reviews_assigned", "Reviews assigned"],
                 ["review_response_rate", "Response rate"], ["time_to_merge", "Median time to merge"], ["commits", "Commits"]];

  function list(container, headers, rows) {
    container.textContent = "";
    if (!rows.length) { DA.message(container, "None in this window."); return; }
    const head = DA.el("tr", {}, headers.map(function (h) { return DA.el("th", { text: h }); }));
    container.appendChild(DA.el("table", {}, [DA.el("thead", {}, [head]), DA.el("tbody", {}, rows.map(function (r) {
      return DA.el("tr", {}, r.map(function (c) { return DA.el("td", { text: c === null || c === undefined ? "–" : String(c) }); }));
    }))]));
  }

  function day(iso) { return iso ? iso.slice(0, 10) : "–"; }

  DA.page(function render() {
    const s = DA.state();
    if (!s.id) { DA.message(document.getElementById("person-stats"), "Open a person from Rankings."); return; }
    DA.api("/api/people/" + encodeURIComponent(s.id) + DA.query()).then(function (d) {
      document.getElementById("person-name").textContent = d.person.name;
      document.getElementById("person-identities").textContent =
        [d.person.accounts.join(", "), d.person.emails.join(", "), d.window.label].filter(Boolean).join(" · ");
      const commits = document.getElementById("person-commits");
      commits.textContent = "";
      DA.charts.bars(DA.canvas(commits), d.commits_weekly.map(function (w) { return w.week; }), d.commits_weekly.map(function (w) { return w.value; }), "Commits");
      DA.table(commits, ["Week starting", "Commits"], d.commits_weekly.map(function (w) { return [w.week, w.value]; }));
      list(document.getElementById("person-pending"), ["#", "Title", "Repository", "Opened"],
        d.reviews_pending.map(function (p) { return [p.number, p.title, p.repository, day(p.created_at)]; }));
      list(document.getElementById("person-prs"), ["#", "Title", "Repository", "State", "Opened", "Merged"],
        d.pull_requests.map(function (p) { return [p.number, p.title, p.repository, p.state, day(p.created_at), day(p.merged_at)]; }));
      list(document.getElementById("person-reviews"), ["#", "Title", "Repository", "Kind", "When"],
        d.reviews_given.map(function (r) { return [r.number, r.title, r.repository, r.type, day(r.occurred_at)]; }));
    }).catch(function (e) { DA.message(document.getElementById("person-prs"), e.message, "error"); });

    const stats = document.getElementById("person-stats");
    stats.textContent = "";
    STATS.forEach(function (pair) {
      const tile = DA.el("div", { class: "stat" }, [DA.el("strong", { text: "…" }), DA.el("span", { text: pair[1] })]);
      stats.appendChild(tile);
      DA.api("/api/metrics/" + pair[0] + DA.query({ include_inactive: "true" })).then(function (r) {
        const row = (r.rows || []).find(function (x) { return x.person_id === s.id; });
        tile.firstChild.textContent = r.status === "ok" && row ? DA.fmt(row.value, r.unit) : "–";
      }).catch(function () { tile.firstChild.textContent = "–"; });
    });
  });
})();
