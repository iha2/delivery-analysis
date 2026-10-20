(function () {
  "use strict";
  const DA = window.DA;
  let catalog = null;
  const GROUPS = [["impact", "Impact"], ["delivery", "Delivery"], ["participation", "Participation"],
                  ["activity", "Activity (context)"]];

  function fillPicker(picker, chosen) {
    picker.textContent = "";
    const perPerson = catalog.filter(function (m) { return m.kind === "per_person"; });
    GROUPS.forEach(function (g) {
      const members = perPerson.filter(function (m) { return (m.group || "activity") === g[0]; });
      if (!members.length) { return; }
      const optgroup = DA.el("optgroup", { label: g[1] });
      members.forEach(function (m) {
        const label = m.label + (m.status === "waiting" ? " (waiting for " + m.missing.join(", ") + ")" : "");
        optgroup.appendChild(DA.el("option", { value: m.name, text: label, selected: m.name === chosen }));
      });
      picker.appendChild(optgroup);
    });
  }

  function show(container, r) {
    container.textContent = "";
    if (DA.showResult(container, r)) { return; }
    const s = DA.state();
    const withConfidence = r.rows.some(function (row) { return row.confidence; });
    const headers = ["#", "Person", r.label, "Previous", "Trend", "Sample"].concat(withConfidence ? ["Confidence"] : []);
    const head = DA.el("tr", {}, headers.map(function (h, i) {
      return DA.el("th", { class: i >= 2 && i <= 5 ? "num" : "", text: h });
    }));
    const lines = r.rows.map(function (row) {
      const person = row.person_id
        ? DA.el("a", { href: "/person" + DA.query({ id: row.person_id }), text: row.name })
        : DA.el("span", { text: row.name });
      const why = row.unranked_reason ? " (unranked: " + row.unranked_reason + ")" : " (unranked)";
      const cells = [
        DA.el("td", { text: row.rank ? String(row.rank) : "–" }),
        DA.el("td", {}, [person, row.ranked || !row.person_id ? null : DA.el("span", { class: "muted", text: why })]),
        DA.el("td", { class: "num", text: DA.fmt(row.value, r.unit) }),
        DA.el("td", { class: "num", text: DA.fmt(row.previous, r.unit) }),
        DA.el("td", { class: "num" }, [DA.trend(row.trend, r.better)]),
        DA.el("td", { class: "num", text: String(row.sample) }),
      ];
      if (withConfidence) { cells.push(DA.el("td", { text: row.confidence || "–" })); }
      return DA.el("tr", { class: row.ranked ? "" : "unranked" }, cells);
    });
    container.appendChild(DA.el("table", {}, [DA.el("thead", {}, [head]), DA.el("tbody", {}, lines)]));
    if (r.team) {
      container.appendChild(DA.el("p", { class: "note", text: "Team: " + DA.fmt(r.team.value, r.unit) +
        (r.team.p85 !== undefined ? " (85th percentile " + DA.fmt(r.team.p85, r.unit) + ")" : "") +
        " over " + r.team.sample + " · " + r.window.label + (s.team ? "" : " · all repositories") }));
    }
    DA.notes(container, r.notes);
  }

  function render() {
    const picker = document.getElementById("metric-picker");
    const inactive = document.getElementById("include-inactive");
    const container = document.getElementById("ranking");
    const s = DA.state();
    const chosen = s.metric || "impact_points";
    inactive.checked = s.inactive === "1";
    const ready = catalog ? Promise.resolve() : DA.api("/api/metrics").then(function (d) { catalog = d.metrics; });
    ready.then(function () {
      fillPicker(picker, chosen);
      const meta = catalog.find(function (m) { return m.name === chosen; });
      document.getElementById("metric-description").textContent = meta ? meta.description : "";
      return DA.api("/api/metrics/" + chosen + DA.query({ include_inactive: inactive.checked ? "true" : "" }));
    }).then(function (r) { show(container, r); })
      .catch(function (e) { DA.message(container, e.message, "error"); });
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.getElementById("metric-picker").addEventListener("change", function (event) {
      DA.setParam("metric", event.target.value);
      render();
    });
    document.getElementById("include-inactive").addEventListener("change", function (event) {
      DA.setParam("inactive", event.target.checked ? "1" : "");
      render();
    });
  });
  DA.page(render);
})();
