// Member Management: client-side search, filters and sorting.
// No dependencies; server remains authoritative for all data & permissions.
(function () {
  "use strict";
  var input = document.getElementById("member-search");
  var table = document.getElementById("members-table");
  if (!input || !table) return;
  var tbody = table.tBodies[0];
  var rows = Array.from(tbody.rows);
  var count = document.getElementById("member-count");
  var empty = document.getElementById("member-empty");
  var roleSel = document.getElementById("member-role");
  var statusSel = document.getElementById("member-status");
  var sortState = { col: null, dir: 1 };

  function apply() {
    var q = input.value.trim().toLowerCase();
    var role = roleSel ? roleSel.value : "";
    var status = statusSel ? statusSel.value : "";
    var visible = 0;
    for (var i = 0; i < rows.length; i++) {
      var row = rows[i];
      var okQ = !q || row.textContent.toLowerCase().indexOf(q) !== -1;
      var okRole = !role || row.getAttribute("data-role") === role;
      var isActive = row.getAttribute("data-active") === "1";
      var okStatus = !status ||
        (status === "active" && isActive) ||
        (status === "inactive" && !isActive);
      var show = okQ && okRole && okStatus;
      row.style.display = show ? "" : "none";
      if (show) visible++;
    }
    if (count) {
      count.textContent = (q || role || status)
        ? visible + " of " + rows.length + " shown"
        : rows.length + " members";
    }
    if (empty) empty.hidden = visible !== 0;
    if (table) table.style.display = visible === 0 ? "none" : "";
  }
  input.addEventListener("input", apply);
  if (roleSel) roleSel.addEventListener("change", apply);
  if (statusSel) statusSel.addEventListener("change", apply);
  apply();

  // ---- Sorting (click a sortable header to toggle asc/desc) ----
  table.querySelectorAll("th.sortable").forEach(function (th) {
    th.addEventListener("click", function () {
      var col = parseInt(th.getAttribute("data-col"), 10);
      var numeric = th.getAttribute("data-type") === "num";
      sortState.dir = sortState.col === col ? -sortState.dir : 1;
      sortState.col = col;

      var sorted = rows.slice().sort(function (a, b) {
        var av = a.cells[col].textContent.trim();
        var bv = b.cells[col].textContent.trim();
        if (numeric) {
          var an = parseFloat(av) || 0, bn = parseFloat(bv) || 0;
          return (an - bn) * sortState.dir;
        }
        return av.localeCompare(bv, undefined, { sensitivity: "base" }) * sortState.dir;
      });
      var frag = document.createDocumentFragment();
      sorted.forEach(function (r) { frag.appendChild(r); });
      tbody.appendChild(frag);

      table.querySelectorAll("th .sort-indicator").forEach(function (s) {
        s.textContent = "";
      });
      th.querySelector(".sort-indicator").textContent = sortState.dir === 1 ? " ▲" : " ▼";
    });
  });
})();
