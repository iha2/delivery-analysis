/* Shared helpers for every page: API calls, header, pickers, URL state, freshness. */
(function () {
  "use strict";
  const DA = (window.DA = window.DA || {});
  let renderPage = function () {};
  let wasRunning = false;

  DA.api = function (path, options) {
    const opts = options || {};
    const init = { method: opts.method || "GET", headers: {} };
    if (opts.body !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(opts.body);
    }
    return fetch(path, init).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (data) {
        if (!response.ok) { throw new Error(Array.isArray(data.detail) ? data.detail.map(function (item) { return item.msg; }).join("; ") : data.detail || "HTTP " + response.status); }
        return data;
      });
    });
  };

  DA.el = function (tag, attrs, children) {
    const node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (key) {
      const value = attrs[key];
      if (value === undefined || value === null || value === false) { return; }
      if (key === "text") { node.textContent = value; }
      else if (key === "class") { node.className = value; }
      else if (key.indexOf("on") === 0) { node.addEventListener(key.slice(2), value); }
      else { node.setAttribute(key, value === true ? "" : value); }
    });
    (children || []).forEach(function (child) {
      if (child === null || child === undefined) { return; }
      node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
    });
    return node;
  };

  DA.state = function () {
    const params = new URLSearchParams(window.location.search);
    const get = function (name) { return params.get(name) || ""; };
    return { team: get("team"), window: get("window"), from: get("from"), to: get("to"),
             metric: get("metric"), inactive: get("inactive"), id: get("id") };
  };

  DA.query = function (extra) {
    const s = DA.state();
    const params = new URLSearchParams();
    if (s.team) { params.set("team", s.team); }
    if (s.window) { params.set("window", s.window); }
    if (s.window === "custom") { params.set("from", s.from); params.set("to", s.to); }
    Object.keys(extra || {}).forEach(function (key) {
      if (extra[key] !== undefined && extra[key] !== "") { params.set(key, extra[key]); }
    });
    const text = params.toString();
    return text ? "?" + text : "";
  };

  DA.setParam = function (name, value) {
    const params = new URLSearchParams(window.location.search);
    if (value) { params.set(name, value); } else { params.delete(name); }
    const text = params.toString();
    window.history.replaceState(null, "", window.location.pathname + (text ? "?" + text : ""));
    markNav();
  };

  DA.fmt = function (value, unit) {
    if (value === null || value === undefined) { return "–"; }
    if (unit === "ratio") { return Math.round(value * 100) + "%"; }
    if (unit === "hours") { return value >= 48 ? (value / 24).toFixed(1) + " d" : value.toFixed(1) + " h"; }
    if (unit === "usd") { return "$" + value.toFixed(2); }
    if (unit === "points_per_usd") { return value.toFixed(2); }
    if (unit === "multiple") { return value.toFixed(2) + "x"; }
    return Number.isInteger(value) ? String(value) : value.toFixed(1);
  };

  DA.trend = function (trend, better) {
    if (trend === null || trend === undefined) { return DA.el("span", { class: "muted", text: "–" }); }
    const pct = Math.round(trend * 100);
    const up = pct > 0;
    let kind = "";
    if (better === "higher" && pct !== 0) { kind = up ? "good" : "bad"; }
    if (better === "lower" && pct !== 0) { kind = up ? "bad" : "good"; }
    return DA.el("span", { class: kind, text: (up ? "▲ +" : pct < 0 ? "▼ " : "") + pct + "%" });
  };

  DA.ago = function (iso) {
    if (!iso) { return "never"; }
    const minutes = Math.round((Date.now() - Date.parse(iso)) / 60000);
    if (minutes < 1) { return "just now"; }
    if (minutes < 60) { return minutes + " min ago"; }
    if (minutes < 48 * 60) { return Math.round(minutes / 60) + " h ago"; }
    return Math.round(minutes / 1440) + " d ago";
  };

  DA.message = function (container, text, kind) {
    container.textContent = "";
    container.appendChild(DA.el("p", { class: kind || "note", text: text }));
  };

  DA.card = function (container, title, subtitle) {
    const body = DA.el("div", { class: "card-body" });
    container.appendChild(DA.el("section", { class: "card" }, [
      DA.el("h3", { text: title }), subtitle ? DA.el("p", { class: "subtitle", text: subtitle }) : null, body,
    ]));
    return body;
  };

  DA.notes = function (body, notes) {
    if (!notes || !notes.length) { return; }
    body.appendChild(DA.el("ul", { class: "notes" }, notes.map(function (n) { return DA.el("li", { text: n }); })));
  };

  DA.sourceLabel = function (name) {
    const labels = { jira: "Jira", bitbucket: "Bitbucket", claude_usage: "Claude usage", links: "pull request links", confluence: "Confluence" };
    return labels[name] || name.replace("_", " ");
  };

  DA.showResult = function (body, result) {
    if (result.status === "waiting") {
      DA.message(body, "Waiting for " + result.missing.map(DA.sourceLabel).join(" and ") + " data. This fills in when that source is connected.");
      return true;
    }
    if (result.status === "error") {
      DA.message(body, "This metric failed: " + result.error, "error");
      return true;
    }
    return false;
  };

  DA.table = function (body, headers, rows) {
    const head = DA.el("tr", {}, headers.map(function (h) { return DA.el("th", { text: h }); }));
    const lines = rows.map(function (row) {
      return DA.el("tr", {}, row.map(function (cell) { return DA.el("td", { text: String(cell) }); }));
    });
    body.appendChild(DA.el("details", {}, [
      DA.el("summary", { text: "Show as table" }),
      DA.el("table", {}, [DA.el("thead", {}, [head]), DA.el("tbody", {}, lines)]),
    ]));
  };

  let canvasCount = 0;
  DA.canvas = function (body, extra) {
    canvasCount += 1;
    const canvas = DA.el("canvas", { id: "chart-" + canvasCount, role: "img" });
    body.appendChild(DA.el("div", { class: "chart" + (extra ? " " + extra : "") }, [canvas]));
    return canvas;
  };

  function markNav() {
    const query = DA.query();
    document.querySelectorAll("nav#nav a").forEach(function (link) {
      const base = link.getAttribute("data-base") || link.getAttribute("href").split("?")[0];
      link.setAttribute("data-base", base);
      link.setAttribute("href", base + query);
      const here = window.location.pathname === base || (base === "/rankings" && window.location.pathname === "/person");
      link.classList.toggle("active", here);
    });
  }

  function windowOptions() {
    const options = [["", "Team default"], ["30d", "Last 30 days"], ["90d", "Last 90 days"]];
    const now = new Date();
    for (let i = 0; i < 6; i += 1) {
      const month = new Date(now.getFullYear(), now.getMonth() - i, 1);
      const value = "month:" + month.getFullYear() + "-" + String(month.getMonth() + 1).padStart(2, "0");
      options.push([value, month.toLocaleString("en-US", { month: "long", year: "numeric" })]);
    }
    options.push(["custom", "Custom dates"]);
    return options;
  }

  function buildHeader(onChange) {
    const header = document.getElementById("header");
    const s = DA.state();
    const team = DA.el("select", { "aria-label": "Team" }, [DA.el("option", { value: "", text: "All repositories" })]);
    const win = DA.el("select", { "aria-label": "Window" }, windowOptions().map(function (o) {
      return DA.el("option", { value: o[0], text: o[1], selected: o[0] === s.window });
    }));
    const from = DA.el("input", { type: "date", value: s.from, "aria-label": "From" });
    const to = DA.el("input", { type: "date", value: s.to, "aria-label": "To" });
    const custom = DA.el("span", { class: s.window === "custom" ? "" : "hidden" }, [from, " to ", to]);
    const refresh = DA.el("button", { text: "Refresh", onclick: function () { DA.refresh({}); } });
    header.appendChild(DA.el("div", { class: "pickers" }, [
      DA.el("label", {}, ["Team ", team]), DA.el("label", {}, ["Window ", win]), custom, refresh,
    ]));
    header.appendChild(DA.el("div", { class: "chips", "aria-live": "polite" }));
    DA.api("/api/teams").then(function (data) {
      data.teams.forEach(function (t) {
        team.appendChild(DA.el("option", { value: t.team_id, text: t.name, selected: t.team_id === s.team }));
      });
    }).catch(function () {});
    team.addEventListener("change", function () { DA.setParam("team", team.value); onChange(); });
    win.addEventListener("change", function () {
      DA.setParam("window", win.value);
      custom.className = win.value === "custom" ? "" : "hidden";
      if (win.value !== "custom") { onChange(); }
    });
    const customChanged = function () {
      if (from.value && to.value) { DA.setParam("from", from.value); DA.setParam("to", to.value); onChange(); }
    };
    from.addEventListener("change", customChanged);
    to.addEventListener("change", customChanged);
  }

  DA.showSources = function () {
    return DA.api("/api/sources").then(function (data) {
      const chips = document.querySelector("header#header .chips");
      if (!chips) { return data; }
      chips.textContent = "";
      const worst = {};
      data.sources.forEach(function (s) {
        const kind = s.failed ? "failed" : (s.age_minutes === null || s.age_minutes >= data.refresh_after_minutes ? "stale" : "fresh");
        const rank = { fresh: 0, stale: 1, failed: 2 }[kind];
        if (!worst[s.connector] || rank > worst[s.connector].rank) {
          worst[s.connector] = { kind: kind, rank: rank, last: s.last_run, error: s.error };
        }
      });
      data.configured.forEach(function (name) {
        const w = worst[name] || { kind: "stale", last: null, error: null };
        const text = name + (w.kind === "failed" ? " failed" : " synced " + DA.ago(w.last));
        chips.appendChild(DA.el("span", { class: "chip " + w.kind, title: w.error || "", text: text }));
      });
      data.waiting.forEach(function (name) {
        chips.appendChild(DA.el("span", { class: "chip waiting", text: name.replace("_", " ") + " not connected" }));
      });
      if (data.refresh.running) {
        chips.appendChild(DA.el("span", { class: "chip refreshing", text: "refreshing" }));
        wasRunning = true;
        window.setTimeout(DA.showSources, 3000);
      } else if (wasRunning) {
        wasRunning = false;
        renderPage();
      }
      return data;
    }).catch(function () {});
  };

  DA.refresh = function (body) {
    return DA.api("/api/refresh", { method: "POST", body: body || {} })
      .then(function () { return DA.showSources(); })
      .catch(function (error) { window.alert("Refresh failed: " + error.message); });
  };

  DA.page = function (render) {
    document.addEventListener("DOMContentLoaded", function () {
      renderPage = render;
      markNav();
      buildHeader(render);
      render();
      DA.showSources().then(function () { DA.refresh({ only_stale: true }); });
    });
  };
})();
