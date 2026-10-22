/* Trade journal: built from the paper account's fills, not from a sample.

   Numbers come from /api/journal/summary. A missing figure renders as "—", never as zero,
   because "0% win rate" and "no closed trades" are different facts. */
(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
  var chart = null;

  function money(value) {
    var n = Number(value || 0);
    var sign = n < 0 ? "−" : "";
    return sign + "$" + Math.abs(n).toLocaleString("en-US", {
      minimumFractionDigits: 2, maximumFractionDigits: 2
    });
  }

  function setKpi(id, text, tone) {
    var el = $(id);
    if (!el) return;
    el.textContent = text;
    el.className = "value num" + (tone ? " " + tone : "");
  }

  function toneOf(value) {
    if (value === null || value === undefined) return "";
    return value > 0 ? "up-text" : value < 0 ? "down-text" : "";
  }

  function drawEquity(curve) {
    var canvas = $("equity");
    if (!canvas || !window.Chart) return;
    if (chart) { chart.destroy(); chart = null; }

    var values = curve.map(function (p) { return p.value; });
    var first = values.length ? values[0] : 0;
    var up = values.length > 1 && values[values.length - 1] >= first;

    var ctx = canvas.getContext("2d");
    var gradient = ctx.createLinearGradient(0, 0, 0, 320);
    gradient.addColorStop(0, up ? "rgba(20,184,166,.28)" : "rgba(239,68,68,.22)");
    gradient.addColorStop(1, "rgba(20,184,166,0)");

    chart = new Chart(ctx, {
      type: "line",
      data: {
        labels: curve.map(function (p) { return p.date.slice(5); }),
        datasets: [{
          data: values,
          borderColor: up ? "#0d9488" : "#dc2626",
          backgroundColor: gradient,
          fill: true,
          tension: 0.25,
          pointRadius: 0,
          pointHitRadius: 8,
          borderWidth: 2
        }]
      },
      options: {
        animation: false,
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: function (item) { return money(item.parsed.y); }
            }
          }
        },
        scales: {
          x: { grid: { display: false }, ticks: { color: "#94a3b8", font: { size: 10 }, maxTicksLimit: 8 } },
          y: {
            grid: { color: "#eef2f6" },
            ticks: {
              color: "#94a3b8", font: { size: 10 },
              callback: function (v) { return "$" + (v / 1000).toFixed(1) + "k"; }
            }
          }
        }
      }
    });
  }

  function renderMistakes(mistakes) {
    var box = $("mistakes");
    if (!box) return;
    box.innerHTML = "";
    var maxCost = Math.max.apply(null, mistakes.map(function (m) { return m.cost; }).concat([1]));

    mistakes.forEach(function (m) {
      var row = document.createElement("div");
      row.className = "mistake";
      var width = m.cost > 0 ? Math.max(4, (m.cost / maxCost) * 100) : 0;
      row.innerHTML =
        '<div class="row">' +
        '<span class="name">' + m.label + "</span>" +
        '<span class="cost"' + (m.cost > 0 ? "" : ' style="color:var(--muted)"') + ">" +
        (m.cost > 0 ? money(-m.cost) : "—") + "</span>" +
        "</div>" +
        '<div class="desc">' + m.note + " · " +
        (m.count ? m.count + "×" : "never fired") + "</div>" +
        '<div class="bar"><div style="height:100%;width:' + width + "%;background:" +
        (m.cost > 0 ? "var(--down)" : "transparent") + '"></div></div>';
      box.appendChild(row);
    });
  }

  var MONTHS = ["January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December"];

  var calendarMonth = null;   // "2026-07"
  var calendarData = [];      // the /api/journal/summary daily rows

  function pad(n) { return (n < 10 ? "0" : "") + n; }

  function currentMonthKey() {
    var now = new Date();
    return now.getFullYear() + "-" + pad(now.getMonth() + 1);
  }

  // Every month from the first one with a trade through this month, so the switcher can
  // reach back to where the history starts and forward to today.
  function monthRange() {
    var current = currentMonthKey();
    var first = current;
    calendarData.forEach(function (d) {
      var key = d.date.slice(0, 7);
      if (key < first) first = key;
    });
    var months = [];
    var year = parseInt(first.slice(0, 4), 10);
    var month = parseInt(first.slice(5, 7), 10);
    while (months.length < 60) {
      var key = year + "-" + pad(month);
      months.push(key);
      if (key >= current) break;
      month += 1;
      if (month > 12) { month = 1; year += 1; }
    }
    return months;
  }

  function busiestMonth() {
    var counts = {};
    calendarData.forEach(function (d) {
      var key = d.date.slice(0, 7);
      counts[key] = (counts[key] || 0) + 1;
    });
    var best = null;
    var bestCount = -1;
    Object.keys(counts).forEach(function (key) {
      if (counts[key] > bestCount || (counts[key] === bestCount && key > best)) {
        best = key;
        bestCount = counts[key];
      }
    });
    return best;
  }

  function renderHeatmap() {
    var box = $("heatmap");
    if (!box) return;
    box.innerHTML = "";

    var months = monthRange();
    if (!calendarMonth || months.indexOf(calendarMonth) === -1) {
      calendarMonth = busiestMonth() || months[months.length - 1];
    }
    var index = months.indexOf(calendarMonth);

    var year = parseInt(calendarMonth.slice(0, 4), 10);
    var monthIndex = parseInt(calendarMonth.slice(5, 7), 10) - 1;

    $("cal-label").textContent = MONTHS[monthIndex] + " " + year;
    $("cal-prev").disabled = index <= 0;
    $("cal-next").disabled = index >= months.length - 1;

    var inMonth = calendarData.filter(function (d) {
      return d.date.slice(0, 7) === calendarMonth;
    });
    $("calendar-sub").textContent = inMonth.length
      ? inMonth.length + " trading day" + (inMonth.length === 1 ? "" : "s") +
        " · grey days had no trades"
      : "No closed trades this month";

    var byDate = {};
    inMonth.forEach(function (d) { byDate[d.date] = d.pl; });
    var maxAbs = Math.max.apply(null,
      inMonth.map(function (d) { return Math.abs(d.pl); }).concat([1]));
    var daysInMonth = new Date(Date.UTC(year, monthIndex + 1, 0)).getUTCDate();
    var offset = (new Date(Date.UTC(year, monthIndex, 1)).getUTCDay() + 6) % 7; // Monday first

    ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].forEach(function (label) {
      var head = document.createElement("div");
      head.className = "dow";
      head.textContent = label;
      box.appendChild(head);
    });

    for (var blank = 0; blank < offset; blank++) {
      var spacer = document.createElement("div");
      spacer.className = "heat empty";
      box.appendChild(spacer);
    }

    for (var day = 1; day <= daysInMonth; day++) {
      var iso = calendarMonth + "-" + pad(day);
      var pl = byDate[iso];
      var cell = document.createElement("div");
      if (pl === undefined) {
        cell.className = "heat empty";
      } else if (pl === 0) {
        cell.className = "heat";
      } else {
        var strength = Math.abs(pl) / maxAbs;
        var band = strength > 0.66 ? 3 : strength > 0.33 ? 2 : 1;
        cell.className = "heat " + (pl > 0 ? "pos-" : "neg-") + band;
      }
      cell.textContent = day;
      if (pl !== undefined) cell.title = iso + ": " + money(pl);
      box.appendChild(cell);
    }
  }

  function shiftMonth(direction) {
    var months = monthRange();
    var index = months.indexOf(calendarMonth);
    var next = index + direction;
    if (next < 0 || next >= months.length) return;
    calendarMonth = months[next];
    renderHeatmap();
  }

  function renderDrills(data) {
    var drills = [];
    if (data.closed_trades < 5) {
      drills.push("Place at least five more papertrades before drawing any conclusion — the sample is too small.");
    }
    if (data.profit_factor !== null && data.profit_factor < 1) {
      drills.push("Cap risk per trade at 2% of equity. Your gross losses now exceed gross wins.");
    }
    if (data.avg_loss && data.avg_win && data.avg_loss > data.avg_win) {
      drills.push("Write the exit before the entry: your average loss (" + money(data.avg_loss) +
        ") is larger than your average win (" + money(data.avg_win) + ").");
    }
    if (data.max_drawdown_pct && data.max_drawdown_pct > 10) {
      drills.push("Set a weekly loss limit. A " + data.max_drawdown_pct.toFixed(1) +
        "% drawdown should stop trading for the week, not increase position size.");
    }
    if (!drills.length) {
      drills.push("Keep a fixed size for the next ten trades and compare the result with your variable sizing.");
      drills.push("Log the reason for every entry in the paper account before you place it.");
    }
    var list = $("drills");
    list.innerHTML = "";
    drills.slice(0, 3).forEach(function (text) {
      var li = document.createElement("li");
      li.textContent = text;
      list.appendChild(li);
    });
  }

  function render(data) {
    setKpi("kpi-net", money(data.net_pl), toneOf(data.net_pl));
    $("kpi-net-sub").textContent =
      (data.return_pct === null ? "—" : (data.return_pct >= 0 ? "+" : "") + data.return_pct + "%") +
      " of " + money(data.starting_cash) + " start";

    setKpi("kpi-win", data.win_rate === null ? "—" : data.win_rate + "%");
    $("kpi-win-sub").textContent =
      data.closed_trades + " closed trade" + (data.closed_trades === 1 ? "" : "s");

    setKpi("kpi-pf", data.profit_factor === null ? "—" : data.profit_factor.toFixed(2),
      data.profit_factor !== null && data.profit_factor < 1 ? "down-text" : "");
    $("kpi-pf-sub").textContent = data.profit_factor === null
      ? "No losing trade yet"
      : data.profit_factor >= 1 ? "Wins outweigh losses" : "Losses outweigh wins";

    setKpi("kpi-dd", data.max_drawdown ? money(-data.max_drawdown) : "—", "down-text");
    $("kpi-dd-sub").textContent = data.peak_at
      ? data.peak_at + " → " + data.trough_at + " (" + (data.max_drawdown_pct || 0) + "%)"
      : "No drawdown yet";

    drawEquity(data.equity_curve);
    renderMistakes(data.mistakes);
    calendarData = data.daily || [];
    renderHeatmap();
    renderDrills(data);

    $("diagnosis-body").textContent = data.verdict;
    var tags = $("diagnosis-tags");
    tags.innerHTML = "";
    data.mistakes.slice(0, 2).forEach(function (m) {
      if (!m.count) return;
      var span = document.createElement("span");
      span.className = "tag";
      span.textContent = m.rule;
      tags.appendChild(span);
    });

    $("journal-sub").textContent =
      data.closed_trades + " closed trades · " + data.open_positions + " open · " +
      "equity " + money(data.equity);
    $("journal-source-tag").textContent = data.simulated ? "paper account" : "live account";
  }

  function load() {
    fetch("/api/journal/summary", { headers: { Accept: "application/json" } })
      .then(function (r) { if (!r.ok) throw new Error("journal " + r.status); return r.json(); })
      .then(render)
      .catch(function (e) { $("diagnosis-body").textContent = "Could not load the journal: " + e.message; });
  }

  document.addEventListener("DOMContentLoaded", function () {
    $("journal-refresh").addEventListener("click", load);
    $("cal-prev").addEventListener("click", function () { shiftMonth(-1); });
    $("cal-next").addEventListener("click", function () { shiftMonth(1); });
    load();
    setInterval(load, 60000);
  });
})();
