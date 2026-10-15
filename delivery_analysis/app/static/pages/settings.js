(function () {
  "use strict";
  const DA = window.DA;
  DA.page(function render() {
    const box = document.getElementById("settings");
    DA.api("/api/settings").then(function (s) {
      box.textContent = "";
      const rows = [
        ["Report time zone", s.report_tz], ["Default window", s.window_days + " days"],
        ["Re-sync overlap", s.overlap_days + " days"], ["Refresh after", s.refresh_after_minutes + " minutes (REFRESH_AFTER_MINUTES)"],
        ["Database", s.database],
      ].concat(Object.keys(s.credentials).map(function (name) {
        return [name, s.credentials[name] ? "present" : "missing"];
      }));
      box.appendChild(DA.el("table", {}, [DA.el("tbody", {}, rows.map(function (r) {
        return DA.el("tr", {}, [DA.el("th", { text: r[0] }), DA.el("td", { text: r[1] })]);
      }))]));
    }).catch(function (e) { DA.message(box, e.message, "error"); });
  });
})();
