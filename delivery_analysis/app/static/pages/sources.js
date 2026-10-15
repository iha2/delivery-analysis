(function () {
  "use strict";
  const DA = window.DA;

  function stateText(refresh) {
    if (refresh.running) { return "Refreshing" + (refresh.source ? " " + refresh.source : "") + (refresh.full ? " (full)" : "") + " since " + DA.ago(refresh.started_at) + "…"; }
    if (refresh.error) { return "Last refresh failed: " + refresh.error; }
    if (refresh.finished_at) { return "Last refresh " + DA.ago(refresh.finished_at) + ": " + (refresh.summary || "done"); }
    return "No refresh has run since the app started.";
  }

  function render() {
    const list = document.getElementById("source-list");
    Promise.all([DA.api("/api/sources"), DA.api("/api/repos")]).then(function (both) {
      const data = both[0];
      const detail = {};
      both[1].repos.forEach(function (r) { detail[r.repository_id] = r.detail_done + " of " + r.detail_total; });
      document.getElementById("refresh-state").textContent = stateText(data.refresh);
      list.textContent = "";
      if (!data.sources.length) { DA.message(list, data.configured.length ? "Nothing synced yet. Use Refresh now." : "No connectors are configured. Put BITBUCKET in .env."); return; }
      const head = DA.el("tr", {}, ["Source", "Scope", "Status", "Last sync", "Review detail", ""].map(function (h) { return DA.el("th", { text: h }); }));
      const rows = data.sources.map(function (s) {
        const full = DA.el("button", { text: "Full resync", onclick: function () {
          if (window.confirm("Clear the " + s.connector + " cursor and sync its whole window again?")) {
            DA.refresh({ source: s.connector, full: true }).then(render);
          }
        } });
        return DA.el("tr", {}, [
          DA.el("td", { text: s.connector }),
          DA.el("td", { text: s.label }),
          DA.el("td", { class: s.failed ? "error" : "", text: s.status + (s.error ? ": " + s.error : "") }),
          DA.el("td", { text: DA.ago(s.last_run) }),
          DA.el("td", { text: detail[s.scope] || "–" }),
          DA.el("td", {}, [full]),
        ]);
      });
      list.appendChild(DA.el("table", {}, [DA.el("thead", {}, [head]), DA.el("tbody", {}, rows)]));
      if (data.waiting.length) {
        list.appendChild(DA.el("p", { class: "note", text: "Not connected yet: " + data.waiting.join(", ") + "." }));
      }
    }).catch(function (e) { DA.message(list, e.message, "error"); });
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.getElementById("refresh-all").addEventListener("click", function () { DA.refresh({}).then(render); });
  });
  DA.page(render);
})();
