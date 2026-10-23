/* US market dashboard: real numbers from the configured feed via /api/public/us/market.

   Every figure on this page is what the broker reported. Nothing is estimated, and a
   missing price stays "—". The screen below the charts is a *filter with visible rules*,
   never a recommendation: the product must not issue buy signals. */
(function () {
  "use strict";

  var S = {
    en: {
      brand_sub: "Trading recovery platform",
      nav_dashboard: "Dashboard", nav_journal: "Trade journal", nav_papertrade: "Papertrade",
      nav_diagnosis: "Diagnosis",
      m_side_footer: "Market data",
      m_title: "US market",
      m_sub: "Top companies by market value",
      m_dist: "Today's moves",
      m_dist_sub: "How many of the 100 are up, flat or down",
      m_news: "Market news",
      m_news_sub: "Today's headlines, via Yahoo Finance",
      m_screen: "Stocks matching the screen",
      m_screen_sub: "Up 1–10% today · market value over $50B · volume over 2M shares",
      m_screen_note: "A screen is a filter, not a recommendation. These rows are the stocks that matched the rules above, nothing more — TradeRevive AI does not tell you what to buy.",
      m_table: "All 100, sortable",
      m_table_sub: "Click a column to sort, or search by code or name",
      m_th_symbol: "Symbol", m_th_name: "Name", m_th_last: "Last",
      m_th_change: "Change", m_th_volume: "Volume", m_th_cap: "Market cap",
      m_disclaimer: "Market data is provided by Yahoo Finance for information only. It is not financial advice, not a prediction, and not a recommendation. Verify every number with your broker before acting.",
      m_live: "live", m_offline: "offline", m_warming: "loading…",
      m_up: "up", m_down: "down", m_flat: "flat", m_stocks: "stocks",
      m_no_match: "No stock matches that search.",
      m_empty_screen: "Nothing matches the screen right now.",
      m_updated: "updated", m_ago: "ago", m_not_advice: "data, not advice",
      m_flat_bucket: "flat"
    },
    ms: {
      brand_sub: "Platform pemulihan dagangan",
      nav_dashboard: "Papan pemuka", nav_journal: "Jurnal dagangan", nav_papertrade: "Dagangan kertas",
      nav_diagnosis: "Diagnosis",
      m_side_footer: "Data pasaran langsung · Yahoo Finance",
      m_title: "Pasaran AS",
      m_sub: "Syarikat terbesar mengikut nilai pasaran, daripada Yahoo Finance",
      m_dist: "Pergerakan hari ini",
      m_dist_sub: "Berapa daripada 100 itu naik, mendatar atau turun",
      m_news: "Berita pasaran",
      m_news_sub: "Tajuk hari ini, melalui Yahoo Finance",
      m_screen: "Saham yang memenuhi saringan",
      m_screen_sub: "Naik 1–10% hari ini · nilai pasaran melebihi $50B · volum melebihi 2J saham",
      m_screen_note: "Saringan ialah penapis, bukan cadangan. Baris ini ialah saham yang memenuhi peraturan di atas, tidak lebih — TradeRevive AI tidak memberitahu anda apa yang perlu dibeli.",
      m_table: "Kesemua 100, boleh diisih",
      m_table_sub: "Klik lajur untuk mengisih, atau cari mengikut kod atau nama",
      m_th_symbol: "Simbol", m_th_name: "Nama", m_th_last: "Terakhir",
      m_th_change: "Perubahan", m_th_volume: "Volum", m_th_cap: "Nilai pasaran",
      m_disclaimer: "Data pasaran disediakan oleh Yahoo Finance untuk maklumat sahaja. Ia bukan nasihat kewangan, bukan ramalan, dan bukan cadangan. Sahkan setiap nombor dengan broker anda sebelum bertindak.",
      m_live: "langsung", m_offline: "terputus", m_warming: "memuatkan…",
      m_up: "naik", m_down: "turun", m_flat: "mendatar", m_stocks: "saham",
      m_no_match: "Tiada saham sepadan dengan carian itu.",
      m_empty_screen: "Tiada apa yang memenuhi saringan sekarang.",
      m_updated: "dikemas kini", m_ago: "lalu", m_not_advice: "data, bukan nasihat",
      m_flat_bucket: "mendatar"
    }
  };

  var lang = "en";
  var data = null;
  var error = null;
  var sort = "market_cap";
  var dir = "desc";
  var query = "";
  var distChart = null;

  function t(key) { return (S[lang] && S[lang][key]) || S.en[key] || key; }
  function $(id) { return document.getElementById(id); }

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function px(value) {
    if (value === null || value === undefined) return "—";
    return Number(value).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function count(value) {
    if (value === null || value === undefined) return "—";
    return Number(value).toLocaleString("en-US");
  }

  function compact(value) {
    if (value === null || value === undefined) return "—";
    var v = Number(value);
    if (!isFinite(v) || !v) return "—";
    var units = [["T", 1e12], ["B", 1e9], ["M", 1e6], ["K", 1e3]];
    for (var i = 0; i < units.length; i++) {
      if (Math.abs(v) >= units[i][1]) return (v / units[i][1]).toFixed(2) + units[i][0];
    }
    return String(Math.round(v));
  }

  function shortCode(code) { return String(code || "").replace(/^US\./, ""); }

  // ------------------------------------------------------------------ charts

  function drawDistribution(rows) {
    var canvas = $("chart-dist");
    if (!canvas || !window.Chart) return;
    var buckets = [
      { label: "≤ −5%", test: function (c) { return c <= -5; } },
      { label: "−5 – −2%", test: function (c) { return c > -5 && c <= -2; } },
      { label: "−2 – 0%", test: function (c) { return c > -2 && c < 0; } },
      { label: t("m_flat_bucket"), test: function (c) { return c === 0; } },
      { label: "0 – 2%", test: function (c) { return c > 0 && c < 2; } },
      { label: "2 – 5%", test: function (c) { return c >= 2 && c < 5; } },
      { label: "≥ 5%", test: function (c) { return c >= 5; } }
    ];
    var counts = buckets.map(function (b) {
      return rows.filter(function (r) {
        return r.change_rate !== null && r.change_rate !== undefined && b.test(r.change_rate);
      }).length;
    });
    var colours = counts.map(function (_, i) {
      return i < 3 ? "rgba(239, 68, 68, .85)" : i === 3 ? "rgba(148, 163, 184, .85)" : "rgba(20, 184, 166, .85)";
    });

    if (distChart) { distChart.destroy(); distChart = null; }
    distChart = new Chart(canvas.getContext("2d"), {
      type: "bar",
      data: {
        labels: buckets.map(function (b) { return b.label; }),
        datasets: [{ data: counts, backgroundColor: colours, borderRadius: 5, maxBarThickness: 46 }]
      },
      options: {
        animation: false,
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false }, tooltip: { callbacks: {
          label: function (item) { return item.parsed.y + " " + t("m_stocks"); }
        } } },
        scales: {
          x: { grid: { display: false }, ticks: { color: "#64748b", font: { size: 11 } } },
          y: { beginAtZero: true, grid: { color: "#eef2f6" }, ticks: { color: "#94a3b8", precision: 0, font: { size: 11 } } }
        }
      }
    });
  }

  // ------------------------------------------------------------------ screen

  var SCREEN = {
    minChange: 1,
    maxChange: 10,
    minCap: 50e9,
    minVolume: 2e6,
    limit: 8
  };

  function screenRows(rows) {
    return rows.filter(function (r) {
      if (r.change_rate === null || r.change_rate === undefined) return false;
      if (!r.market_cap || !r.volume) return false;
      return r.change_rate >= SCREEN.minChange &&
        r.change_rate <= SCREEN.maxChange &&
        r.market_cap >= SCREEN.minCap &&
        r.volume >= SCREEN.minVolume;
    })
      .sort(function (a, b) { return b.change_rate - a.change_rate; })
      .slice(0, SCREEN.limit);
  }

  function renderScreen(rows) {
    var body = $("screen-body");
    if (!body) return;
    body.innerHTML = "";
    var picks = screenRows(rows);
    if (!picks.length) {
      body.innerHTML = '<tr><td colspan="6" style="color:var(--muted)">' + t("m_empty_screen") + "</td></tr>";
      return;
    }
    picks.forEach(function (r) {
      var tr = document.createElement("tr");
      tr.innerHTML =
        "<td><strong>" + escapeHtml(shortCode(r.symbol)) + "</strong></td>" +
        '<td class="name-cell">' + escapeHtml(r.name || "") + "</td>" +
        '<td class="num">' + px(r.last_price) + "</td>" +
        '<td class="num up-text">+' + Number(r.change_rate).toFixed(2) + "%</td>" +
        '<td class="num">' + compact(r.volume) + "</td>" +
        '<td class="num">' + compact(r.market_cap) + "</td>";
      body.appendChild(tr);
    });
  }

  // ------------------------------------------------------------------- table

  function renderTable(rows) {
    var body = document.querySelector("#us-table tbody");
    if (!body) return;
    body.innerHTML = "";
    if (!rows.length) {
      body.innerHTML = '<tr><td colspan="6" style="color:var(--muted)">' + t("m_no_match") + "</td></tr>";
      return;
    }
    rows.forEach(function (r) {
      var change = r.change_rate;
      var cls = change === null || change === undefined ? "" : (change >= 0 ? "up-text" : "down-text");
      var text = change === null || change === undefined
        ? "—"
        : (change >= 0 ? "+" : "") + Number(change).toFixed(2) + "%";
      var tr = document.createElement("tr");
      tr.innerHTML =
        "<td><strong>" + escapeHtml(shortCode(r.symbol)) + "</strong></td>" +
        '<td class="name-cell">' + escapeHtml(r.name || "") + "</td>" +
        '<td class="num">' + px(r.last_price) + "</td>" +
        '<td class="num ' + cls + '">' + text + "</td>" +
        '<td class="num">' + compact(r.volume) + "</td>" +
        '<td class="num">' + compact(r.market_cap) + "</td>";
      body.appendChild(tr);
    });
  }

  function sortRows(rows) {
    var copy = rows.slice();
    var text = sort === "symbol" || sort === "name";
    copy.sort(function (a, b) {
      var av = a[sort];
      var bv = b[sort];
      if (av === null || av === undefined) return 1;
      if (bv === null || bv === undefined) return -1;
      if (text) {
        av = String(av).toLowerCase();
        bv = String(bv).toLowerCase();
        return av < bv ? -1 : av > bv ? 1 : 0;
      }
      return dir === "desc" ? bv - av : av - bv;
    });
    return copy;
  }

  // ------------------------------------------------------------------- news

  function ago(iso) {
    if (!iso) return "";
    var then = new Date(iso).getTime();
    if (isNaN(then)) return "";
    var mins = Math.max(0, Math.round((Date.now() - then) / 60000));
    if (mins < 60) return mins + "m ago";
    var hours = Math.round(mins / 60);
    if (hours < 24) return hours + "h ago";
    return Math.round(hours / 24) + "d ago";
  }

  function renderNews(data) {
    var list = $("news-list");
    var note = $("news-note");
    if (!list) return;
    list.innerHTML = "";

    var items = (data && data.items) || [];
    if (!items.length) {
      list.innerHTML = '<li class="news-empty">' +
        (data && data.error ? escapeHtml(data.error) : "No headlines came back.") + "</li>";
      note.hidden = true;
      return;
    }

    items.forEach(function (item) {
      var li = document.createElement("li");
      li.className = "news-item";
      li.innerHTML =
        '<a href="' + escapeHtml(item.link) + '" target="_blank" rel="noopener">' +
        escapeHtml(item.title) + "</a>" +
        '<div class="news-meta">' + escapeHtml(item.publisher || "") +
        (item.published ? " · " + escapeHtml(ago(item.published)) : "") + "</div>";
      list.appendChild(li);
    });

    if (data.error) {
      note.hidden = false;
      note.textContent = data.error + " (showing the last headlines fetched)";
    } else if (data.age_seconds !== null && data.age_seconds !== undefined) {
      note.hidden = false;
      note.textContent = "updated " + Math.round(data.age_seconds) + "s ago · " +
        (data.symbols || []).join(", ");
    }
  }

  function loadNews() {
    fetch("/api/public/news?limit=6", { headers: { Accept: "application/json" } })
      .then(function (r) {
        if (!r.ok) throw new Error("news " + r.status);
        return r.json();
      })
      .then(renderNews)
      .catch(function (e) { renderNews({ items: [], error: e.message }); });
  }

  // ------------------------------------------------------------------ render

  function formatPrice(value) {
    if (value === null || value === undefined) return "—";
    if (Math.abs(value) >= 1000) return value.toLocaleString("en-US", { maximumFractionDigits: 2 });
    if (Math.abs(value) >= 1) return value.toFixed(2);
    return value.toFixed(4);
  }

  function renderOverview(payload) {
    var grid = document.getElementById("overview-grid");
    var note = document.getElementById("overview-note");
    if (!grid) return;

    var groups = (payload && payload.groups) || [];
    if (!groups.length) {
      hideOverview();
      return;
    }

    grid.innerHTML = "";
    groups.forEach(function (group) {
      var box = document.createElement("div");
      box.className = "overview-group";

      var title = document.createElement("h3");
      title.textContent = group.title;
      box.appendChild(title);

      if (!group.items || !group.items.length) {
        var err = document.createElement("p");
        err.className = "ov-error";
        err.textContent = group.error || "no data";
        box.appendChild(err);
        grid.appendChild(box);
        return;
      }

      group.items.forEach(function (item) {
        var row = document.createElement("div");
        row.className = "overview-row";

        var label = document.createElement("span");
        label.className = "ov-label";
        label.textContent = item.label;
        label.title = item.symbol;

        var right = document.createElement("span");
        right.className = "ov-right";

        var price = document.createElement("span");
        price.className = "ov-price";
        price.textContent = formatPrice(item.price);

        var change = document.createElement("span");
        var pct = item.change_pct;
        change.className = "ov-change " + (pct === null || pct === undefined
          ? "flat" : pct > 0 ? "up" : pct < 0 ? "down" : "flat");
        change.textContent = pct === null || pct === undefined
          ? "" : (pct > 0 ? "+" : "") + pct.toFixed(2) + "%";

        right.appendChild(price);
        right.appendChild(document.createTextNode(" "));
        right.appendChild(change);
        row.appendChild(label);
        row.appendChild(right);
        box.appendChild(row);
      });

      grid.appendChild(box);
    });

    if (note) note.textContent = payload.source ? "from " + payload.source : "";
  }

  function hideOverview() {
    var card = document.querySelector(".overview-card");
    if (card) card.hidden = true;
  }

  function loadOverview() {
    fetch("/api/public/overview", { headers: { Accept: "application/json" } })
      .then(function (response) {
        if (!response.ok) throw new Error("overview " + response.status);
        return response.json();
      })
      .then(renderOverview)
      .catch(function () {
        // 404 (an older build) or an unreachable feed: no card rather than an empty one.
        hideOverview();
      });
  }

  function render() {
    var status = $("m-status");
    var note = $("m-note");

    if (!data) {
      status.textContent = t("m_offline");
      status.style.background = "#fef2f2";
      status.style.color = "#991b1b";
      if (error) { note.hidden = false; note.textContent = error; }
      return;
    }

    var ready = data.ready;
    var offline = !ready && !!data.error;
    var webFeed = /yahoo/i.test(data.source || "");
    // A broker socket is "live". A web feed is not, whatever its numbers look like.
    status.textContent = ready
      ? (webFeed ? "Yahoo · may be delayed" : t("m_live"))
      : offline ? t("m_offline") : t("m_warming");
    status.title = webFeed
      ? "Yahoo's feed can be delayed by up to 15 minutes. It is not an exchange feed."
      : "";
    status.style.background = ready ? "#ecfdf5" : offline ? "#fef2f2" : "#f1f5f9";
    status.style.color = ready ? "#047857" : offline ? "#991b1b" : "#475569";

    if (!ready) {
      note.hidden = false;
      note.textContent = data.error || "The first sweep of the market is running — about 20 seconds.";
      // No data means no chart: hide the card rather than showing an empty white box.
      var moves = document.getElementById("moves-card");
      if (moves) moves.style.display = "none";
      return;
    }
    note.hidden = true;
    var movesCard = document.getElementById("moves-card");
    if (movesCard) movesCard.style.display = "";

    var rows = data.rows || [];
    var b = data.breadth || {};

    $("m-breadth").innerHTML =
      '<span class="chip">' + count(b.total) + " " + t("m_stocks") + "</span>" +
      '<span class="chip up">' + count(b.gainers) + " " + t("m_up") + "</span>" +
      '<span class="chip down">' + count(b.losers) + " " + t("m_down") + "</span>" +
      '<span class="chip">' + count(b.flat) + " " + t("m_flat") + "</span>" +
      (b.unpriced ? '<span class="chip">' + count(b.unpriced) + " —</span>" : "");

    drawDistribution(rows);
    renderScreen(rows);

    var filtered = query
      ? rows.filter(function (r) {
          var needle = query.toLowerCase();
          return String(r.symbol).toLowerCase().indexOf(needle) !== -1 ||
            String(r.name).toLowerCase().indexOf(needle) !== -1;
        })
      : rows;

    renderTable(sortRows(filtered));

    $("us-page").textContent = filtered.length + " / " + rows.length;
    var meta = [];
    if (data.age_seconds !== null && data.age_seconds !== undefined) {
      meta.push(t("m_updated") + " " + Math.round(data.age_seconds) + "s " + t("m_ago"));
    }
    $("us-meta").textContent = meta.join(" · ");

    document.querySelectorAll("#us-table th.sortable").forEach(function (th) {
      if (th.getAttribute("data-sort") === sort) {
        th.setAttribute("aria-sort", dir === "desc" ? "descending" : "ascending");
      } else {
        th.removeAttribute("aria-sort");
      }
    });
  }

  // -------------------------------------------------------------------- load

  function load() {
    fetch("/api/public/us/market?size=500&sort=" + encodeURIComponent(sort) + "&dir=" + dir, {
      headers: { Accept: "application/json" }
    })
      .then(function (response) {
        if (response.status === 404) throw new Error("The public dashboard is switched off.");
        if (!response.ok) throw new Error("Market request failed (" + response.status + ").");
        return response.json();
      })
      .then(function (payload) {
        applySource(payload);
        return payload;
      })
      .then(function (payload) { data = payload; error = null; render(); retryIfWarming(); })
      .catch(function (err) { data = null; error = err.message; render(); retryIfWarming(); });
  }

  // The first sweep of the US market takes about 20 seconds. Polling every 30s means the
  // page can sit on "loading" long after the data is there, so ask again sooner.
  function retryIfWarming() {
    if (!data || !data.ready) setTimeout(load, 3000);
  }

  function applyLanguage(next) {
    lang = next;
    document.documentElement.lang = next === "ms" ? "ms" : "en";
    document.querySelectorAll("[data-i18n]").forEach(function (el) {
      var key = el.getAttribute("data-i18n");
      if (S[lang][key]) el.textContent = S[lang][key];
    });
    $("lang-en").setAttribute("aria-pressed", String(next === "en"));
    $("lang-ms").setAttribute("aria-pressed", String(next === "ms"));
    if (data && data.ready) render();
  }

  // Name the feed that is actually serving prices, rather than the one we used last week.
  function applySource(payload) {
    var source = (payload && payload.source) || "market data";
    var sub = $("m-sub");
    if (sub && payload && payload.total) {
      sub.textContent = "The largest US companies by market value — " + payload.total +
        " priced now, from " + source;
    }
    var dist = $("m-dist-sub");
    if (dist && payload && payload.total) {
      dist.textContent = "How many of the " + payload.total + " are up, flat or down";
    }
    var footer = $("m-footer");
    if (footer) footer.textContent = "Market data · " + source;
    // The status tag says "live" when a broker socket is up. Yahoo is a web feed and can
    // lag by up to fifteen minutes, so it must not wear the same word.
    var badge = $("m-status");
    if (badge && /yahoo/i.test(source)) {
      badge.textContent = "Yahoo · may be delayed";
      badge.title = "Yahoo's feed can be delayed by up to 15 minutes. It is not an exchange feed.";
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    loadOverview();
    setInterval(loadOverview, 60000);
    applyLanguage("en");

    $("lang-en").addEventListener("click", function () { applyLanguage("en"); });
    $("lang-ms").addEventListener("click", function () { applyLanguage("ms"); });

    document.querySelectorAll("#us-table th.sortable").forEach(function (th) {
      th.addEventListener("click", function () {
        var key = th.getAttribute("data-sort");
        if (sort === key) {
          dir = dir === "desc" ? "asc" : "desc";
        } else {
          sort = key;
          dir = key === "symbol" || key === "name" ? "asc" : "desc";
        }
        if (data && data.ready) render();
      });
    });

    var search = $("us-search");
    var timer = null;
    search.addEventListener("input", function () {
      clearTimeout(timer);
      timer = setTimeout(function () {
        query = search.value.trim();
        if (data && data.ready) render();
      }, 200);
    });

    load();
    loadNews();
    setInterval(load, 30000);
    setInterval(loadNews, 600000);   // Yahoo's feed changes slower than the market does
  });
})();
