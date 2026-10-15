(function () {
  "use strict";
  const DA = window.DA;

  function table(container, headers, rows) {
    container.textContent = "";
    const head = DA.el("tr", {}, headers.map(function (h) { return DA.el("th", { text: h }); }));
    container.appendChild(DA.el("table", {}, [DA.el("thead", {}, [head]), DA.el("tbody", {}, rows)]));
  }

  function teams() {
    const list = document.getElementById("team-list");
    DA.api("/api/teams").then(function (data) {
      list.textContent = "";
      if (!data.teams.length) { DA.message(list, "No teams yet. Create one below from the selected repositories."); return; }
      table(list, ["Team", "Repositories", "Active", "Inactive", "Excluded"], data.teams.map(function (t) {
        return DA.el("tr", {}, [
          DA.el("td", {}, [DA.el("button", { class: "button-link", text: t.name, onclick: function () { DA.setParam("team", t.team_id); window.location.reload(); } })]),
          DA.el("td", { text: t.repos.map(function (r) { return r.name || r.repository_id; }).join(", ") }),
          DA.el("td", { text: String(t.members.active) }),
          DA.el("td", { text: String(t.members.inactive) }),
          DA.el("td", { text: String(t.members.excluded) }),
        ]);
      }));
    }).catch(function (e) { DA.message(list, e.message, "error"); });
  }

  function repoChoices() {
    const holder = document.getElementById("team-repos");
    DA.api("/api/repos").then(function (data) {
      holder.textContent = "";
      data.repos.forEach(function (r) {
        holder.appendChild(DA.el("label", {}, [
          DA.el("input", { type: "checkbox", value: "bitbucket:" + r.repository_id, checked: true }), " " + r.slug + " ",
        ]));
      });
    }).catch(function () {});
  }

  function members() {
    const s = DA.state();
    const container = document.getElementById("team-members");
    const duplicates = document.getElementById("duplicates");
    duplicates.textContent = "";
    if (!s.team) { DA.message(container, "Pick a team in the header to see and edit its members."); return; }
    DA.api("/api/teams/" + encodeURIComponent(s.team)).then(function (t) {
      document.getElementById("members-title").textContent = "Members of " + t.name;
      table(container, ["Person", "Status", "Last commit", "Emails", ""], t.members.map(function (m) {
        const next = m.status === "excluded" ? "active" : "excluded";
        const button = DA.el("button", { text: next === "excluded" ? "Exclude" : "Include", onclick: function () {
          DA.api("/api/teams/" + encodeURIComponent(t.team_id) + "/members/" + encodeURIComponent(m.person_id),
                 { method: "POST", body: { status: next } }).then(members).catch(function (e) { window.alert(e.message); });
        } });
        return DA.el("tr", { class: m.status === "active" ? "" : "unranked" }, [
          DA.el("td", { text: m.name }),
          DA.el("td", { text: m.status + (m.manual ? " (set by you)" : "") }),
          DA.el("td", { text: m.last_commit ? m.last_commit.slice(0, 10) : "–" }),
          DA.el("td", { text: m.emails.join(", ") }),
          DA.el("td", {}, [button]),
        ]);
      }));
      if (t.possible_duplicates.length) {
        duplicates.appendChild(DA.el("p", { class: "note", text: "Possible duplicates (merge with the teams CLI if they are the same person):" }));
        duplicates.appendChild(DA.el("ul", { class: "notes" }, t.possible_duplicates.map(function (d) {
          return DA.el("li", { text: d.name_a + " and " + d.name_b + " (" + d.reason + ")" });
        })));
      }
    }).catch(function (e) { DA.message(container, e.message, "error"); });
  }

  function unmapped() {
    const container = document.getElementById("unmapped");
    const s = DA.state();
    DA.api("/api/identities/unmapped").then(function (data) {
      if (!data.unmapped.length) { DA.message(container, "Every account with activity is mapped to a person."); return; }
      table(container, ["Account", "Activity", "Who is it?", ""], data.unmapped.map(function (u) {
        const choose = DA.el("select", { "aria-label": "Person" }, [DA.el("option", { value: "", text: "New person…" })].concat(
          data.people.map(function (p) { return DA.el("option", { value: p.person_id, text: p.name }); })));
        const name = DA.el("input", { placeholder: "Name", value: u.name_hint || "", "aria-label": "New person name" });
        const join = DA.el("input", { type: "checkbox", checked: Boolean(s.team), disabled: !s.team });
        const map = DA.el("button", { text: "Map", onclick: function () {
          const body = { source: u.source, account: u.account, team_id: join.checked ? s.team : null };
          if (choose.value) { body.person_id = choose.value; } else { body.new_name = name.value; }
          DA.api("/api/identities", { method: "POST", body: body }).then(function () { unmapped(); members(); })
            .catch(function (e) { window.alert(e.message); });
        } });
        return DA.el("tr", {}, [
          DA.el("td", {}, [DA.el("strong", { text: u.name_hint || "Unknown name" }), DA.el("div", { class: "muted", text: u.source + ":" + u.account })]),
          DA.el("td", { text: String(u.activity) }),
          DA.el("td", {}, [choose, " ", name, DA.el("label", { class: "muted" }, [" ", join, " add to this team"])]),
          DA.el("td", {}, [map]),
        ]);
      }));
    }).catch(function (e) { DA.message(container, e.message, "error"); });
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.getElementById("create-team").addEventListener("submit", function (event) {
      event.preventDefault();
      const message = document.getElementById("create-message");
      const repos = Array.from(document.querySelectorAll("#team-repos input:checked")).map(function (i) { return i.value; });
      DA.api("/api/teams", { method: "POST", body: { name: document.getElementById("team-name").value, repos: repos } })
        .then(function (r) { message.textContent = r.summary; DA.setParam("team", r.team_id); render(); })
        .catch(function (e) { message.textContent = e.message; message.className = "error"; });
    });
  });

  function render() { teams(); repoChoices(); members(); unmapped(); }
  DA.page(render);
})();
