(function () {
  "use strict";
  const DA = window.DA;
  let last = null;

  function sortState(columns) {
    const params = new URLSearchParams(window.location.search);
    const name = params.get("sort") || "impact_points";
    const col = columns.find(function (c) { return c.name === name; });
    if (!col) { return { name: "", dir: "" }; }
    const dir = params.get("dir") || (col.better === "lower" ? "asc" : "desc");
    return { name: name, dir: dir === "asc" ? "asc" : "desc" };
  }

  function cellValue(row, name) {
    const cell = row.cells[name];
    return cell && cell.value !== null && cell.value !== undefined ? cell.value : null;
  }

  function sorted(rows, sort) {
    if (!sort.name) { return rows; }
    const sign = sort.dir === "asc" ? 1 : -1;
    const people = rows.filter(function (row) { return row.person_id; });
    const unmapped = rows.filter(function (row) { return !row.person_id; });
    const present = people.filter(function (row) { return cellValue(row, sort.name) !== null; });
    const absent = people.filter(function (row) { return cellValue(row, sort.name) === null; });
    present.sort(function (a, b) {
      const x = cellValue(a, sort.name);
      const y = cellValue(b, sort.name);
      return x < y ? -sign : x > y ? sign : 0;
    });
    return present.concat(absent, unmapped);
  }

  const GROUPS = [["impact", "Impact"], ["delivery", "Delivery"], ["participation", "Participation"]];

  // The API names each column's group; this map only covers an older API that does not.
  const FALLBACK_GROUP = { "impact_points": "impact", "impact_per_dollar": "impact", "cost_spent": "impact",
    "delivery_points": "delivery", "delivery_speed": "delivery", "durability": "delivery",
    "participation_points": "participation", "prs_reviewed": "participation", "review_value": "participation",
    "review_responsiveness": "participation" };

  function groupOf(col) { return col.group || FALLBACK_GROUP[col.name] || ""; }

  function startsGroup(shown, i) { return i === 0 || groupOf(shown[i - 1]) !== groupOf(shown[i]); }

  function cellClass(shown, i) {
    return "num" + (groupOf(shown[i]) === "impact" ? " group-impact" : "") + (startsGroup(shown, i) ? " group-start" : "");
  }

  function clickHeader(col) {
    const sort = sortState(last.columns);
    let dir = col.better === "lower" ? "asc" : "desc";
    if (sort.name === col.name) { dir = sort.dir === "asc" ? "desc" : "asc"; }
    DA.setParam("sort", col.name);
    DA.setParam("dir", dir);
    show(document.getElementById("people-matrix"), last);
  }

  function show(container, r) {
    container.textContent = "";
    const shown = r.columns.filter(function (c) { return c.status === "ok"; });
    const waiting = r.columns.filter(function (c) { return c.status === "waiting"; });
    const sort = sortState(shown);
    const groupCells = [DA.el("th", { class: "sticky-col", rowspan: "2", text: "Person" })];
    GROUPS.forEach(function (g) {
      const members = shown.filter(function (c) { return groupOf(c) === g[0]; });
      if (!members.length) { return; }
      groupCells.push(DA.el("th", {
        class: "group-label group-start" + (g[0] === "impact" ? " group-impact" : ""),
        colspan: String(members.length), text: g[1],
      }));
    });
    const groupRow = DA.el("tr", {}, groupCells);
    const head = DA.el("tr", {}, shown.map(function (col, i) {
      const mark = sort.name === col.name ? (sort.dir === "asc" ? " ▲" : " ▼") : "";
      return DA.el("th", {
        class: cellClass(shown, i) + " sortable", title: col.description, tabindex: "0", text: col.label + mark,
        "aria-sort": sort.name === col.name ? (sort.dir === "asc" ? "ascending" : "descending") : null,
        onclick: function () { clickHeader(col); },
        onkeydown: function (event) { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); clickHeader(col); } },
      });
    }));
    const lines = sorted(r.rows, sort).map(function (row) {
      const person = row.person_id
        ? DA.el("a", { href: "/person" + DA.query({ id: row.person_id }), text: row.name })
        : DA.el("span", { text: row.name });
      const cells = shown.map(function (col, i) {
        const cell = row.cells[col.name];
        if (!cell) { return DA.el("td", { class: cellClass(shown, i), text: "–" }); }
        // A reason explains a blank or unranked cell, so it reads as explained rather than broken.
        const blank = cell.value === null || cell.value === undefined;
        const sample = cell.sample === null || cell.sample === undefined ? null : "sample " + cell.sample;
        return DA.el("td", {
          class: cellClass(shown, i) + (cell.ranked ? "" : " unranked") + (cell.reason ? " cell-reason" : ""),
          title: cell.reason || sample,
          text: blank ? "–" : DA.fmt(cell.value, col.unit),
        });
      });
      return DA.el("tr", {}, [DA.el("td", { class: "sticky-col" }, [person])].concat(cells));
    });
    container.appendChild(DA.el("div", { class: "table-scroll" }, [
      DA.el("table", {}, [DA.el("thead", {}, [groupRow, head]), DA.el("tbody", {}, lines)]),
    ]));
    if (waiting.length) {
      const text = waiting.map(function (c) { return c.label + " (waiting for " + c.missing.join(", ") + ")"; }).join("; ");
      container.appendChild(DA.el("p", { class: "note", text: "Not shown yet: " + text }));
    }
    DA.notes(container, r.notes);
  }

  function render() {
    const inactive = document.getElementById("include-inactive");
    const container = document.getElementById("people-matrix");
    inactive.checked = DA.state().inactive === "1";
    DA.api("/api/people-matrix" + DA.query({ include_inactive: inactive.checked ? "true" : "" }))
      .then(function (r) { last = r; show(container, r); })
      .catch(function (e) { DA.message(container, e.message, "error"); });
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.getElementById("include-inactive").addEventListener("change", function (event) {
      DA.setParam("inactive", event.target.checked ? "1" : "");
      render();
    });
  });
  DA.page(render);
})();
