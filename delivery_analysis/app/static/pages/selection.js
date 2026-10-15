(function () {
  "use strict";
  const DA = window.DA;

  function render() {
    const list = document.getElementById("repo-list");
    DA.api("/api/repos").then(function (data) {
      list.textContent = "";
      if (!data.repos.length) { DA.message(list, "No repositories are selected yet."); return; }
      const head = DA.el("tr", {}, ["Repository", "Status", "Last sync", "Review detail", ""].map(function (h) { return DA.el("th", { text: h }); }));
      const rows = data.repos.map(function (r) {
        const remove = DA.el("button", { text: "Remove", onclick: function () {
          if (!window.confirm("Stop syncing " + r.workspace + "/" + r.slug + "? Stored data is kept.")) { return; }
          DA.api("/api/repos/" + encodeURIComponent(r.repository_id), { method: "DELETE" }).then(render)
            .catch(function (e) { window.alert(e.message); });
        } });
        return DA.el("tr", {}, [
          DA.el("td", {}, [DA.el("strong", { text: r.workspace + "/" + r.slug }), DA.el("div", { class: "muted", text: r.repository_id })]),
          DA.el("td", { class: r.status === "failed" ? "error" : "", text: r.status + (r.error ? ": " + r.error : "") }),
          DA.el("td", { text: DA.ago(r.last_run) }),
          DA.el("td", { text: r.detail_done + " of " + r.detail_total }),
          DA.el("td", {}, [remove]),
        ]);
      });
      list.appendChild(DA.el("table", {}, [DA.el("thead", {}, [head]), DA.el("tbody", {}, rows)]));
    }).catch(function (e) { DA.message(list, e.message, "error"); });
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.getElementById("add-repo").addEventListener("submit", function (event) {
      event.preventDefault();
      const input = document.getElementById("repo-input");
      const message = document.getElementById("add-message");
      const text = input.value.trim();
      if (!text) { return; }
      message.textContent = "Checking…";
      DA.api("/api/repos", { method: "POST", body: { repo: text.indexOf(":") > 0 ? text : "bitbucket:" + text } })
        .then(function (r) { message.textContent = "Added " + r.workspace + "/" + r.slug + "."; input.value = ""; render(); })
        .catch(function (e) { message.textContent = e.message; message.className = "error"; });
    });
  });
  DA.page(render);
})();
