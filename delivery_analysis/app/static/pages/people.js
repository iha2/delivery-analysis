(function () {
  "use strict";
  const DA = window.DA;
  let last = null;

  function sortState(columns) {
    const params = new URLSearchParams(window.location.search);
    const name = params.get("sort") || "";
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
    const head = DA.el("tr", {}, [DA.el("th", { class: "sticky-col", text: "Person" })].concat(shown.map(function (col) {
      const mark = sort.name === col.name ? (sort.dir === "asc" ? " ▲" : " ▼") : "";
      return DA.el("th", {
        class: "num sortable", title: col.description, tabindex: "0", text: col.label + mark,
        "aria-sort": sort.name === col.name ? (sort.dir === "asc" ? "ascending" : "descending") : null,
        onclick: function () { clickHeader(col); },
        onkeydown: function (event) { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); clickHeader(col); } },
      });
    })));
    const lines = sorted(r.rows, sort).map(function (row) {
      const person = row.person_id
        ? DA.el("a", { href: "/person" + DA.query({ id: row.person_id }), text: row.name })
        : DA.el("span", { text: row.name });
      const cells = shown.map(function (col) {
        const cell = row.cells[col.name];
        if (!cell) { return DA.el("td", { class: "num", text: "–" }); }
        return DA.el("td", {
          class: "num" + (cell.ranked ? "" : " unranked"),
          title: cell.sample === null || cell.sample === undefined ? null : "sample " + cell.sample,
          text: DA.fmt(cell.value, col.unit),
        });
      });
      return DA.el("tr", {}, [DA.el("td", { class: "sticky-col" }, [person])].concat(cells));
    });
    container.appendChild(DA.el("div", { class: "table-scroll" }, [
      DA.el("table", {}, [DA.el("thead", {}, [head]), DA.el("tbody", {}, lines)]),
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
