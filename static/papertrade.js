/* Papertrade: simulated orders filled at the broker's last price.

   The account lives on the server, so the page only renders what the API returns. Every
   refusal (no cash, no shares, broker down) is shown verbatim — a silent failure here
   would teach the wrong lesson about how trading works. */
(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
  var lastQuote = null;
  var busy = false;

  function money(value) {
    var n = Number(value || 0);
    return "$" + n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function signed(value) {
    var n = Number(value || 0);
    var cls = n > 0 ? "up-text" : n < 0 ? "down-text" : "";
    return '<span class="' + cls + '">' + (n > 0 ? "+" : "") + money(n).replace("$-", "-$") + "</span>";
  }

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function alertBox(message, kind) {
    var box = $("order-alert");
    box.textContent = message;
    box.hidden = false;
    box.style.background = kind === "ok" ? "#ecfdf5" : "#fef2f2";
    box.style.borderColor = kind === "ok" ? "#a7f3d0" : "#fecaca";
    box.style.color = kind === "ok" ? "#065f46" : "#991b1b";
  }

  // ----------------------------------------------------------------- render

  function renderAccount(account) {
    $("k-cash").textContent = money(account.cash);
    $("k-mv").textContent = money(account.market_value);
    $("k-eq").textContent = money(account.equity);
    $("k-ret").innerHTML = signed(account.total_return);
    $("k-ret").className = "value num " + (account.total_return > 0 ? "up-text" : account.total_return < 0 ? "down-text" : "");
    var pct = account.starting_cash ? (account.total_return / account.starting_cash) * 100 : 0;
    $("k-ret-sub").textContent =
      (pct >= 0 ? "+" : "") + pct.toFixed(2) + "% of " + money(account.starting_cash) + " start";

    var body = document.querySelector("#positions-table tbody");
    body.innerHTML = "";
    if (!account.positions.length) {
      body.innerHTML = '<tr><td colspan="6" class="muted-cell">No open positions.</td></tr>';
    } else {
      account.positions.forEach(function (p) {
        var tr = document.createElement("tr");
        tr.innerHTML =
          "<td><strong>" + escapeHtml(p.symbol.replace(/^US\./, "")) + "</strong></td>" +
          '<td class="num">' + p.quantity + "</td>" +
          '<td class="num">' + money(p.average_cost) + "</td>" +
          '<td class="num">' + money(p.price) + (p.priced ? "" : "<br><span class='muted-cell'>at cost</span>") + "</td>" +
          '<td class="num">' + money(p.market_value) + "</td>" +
          '<td class="num">' + signed(p.unrealised) + "</td>";
        body.appendChild(tr);
      });
    }
    $("unrealised").textContent = account.positions.length
      ? "Unrealised P&L " + money(account.unrealised) + " · realised " + money(account.realised)
      : "Realised P&L " + money(account.realised);
    $("positions-sub").textContent = account.positions.length
      ? "Marked at the latest price from OpenD"
      : "Nothing held right now";

    var fills = document.querySelector("#fills-table tbody");
    fills.innerHTML = "";
    if (!account.fills.length) {
      fills.innerHTML = '<tr><td colspan="7" class="muted-cell">No orders yet. Buy something to begin.</td></tr>';
    } else {
      account.fills.forEach(function (f) {
        var tr = document.createElement("tr");
        var when = String(f.at || "").replace("T", " ").replace(/\+00:00$/, " UTC").slice(0, 19);
        tr.innerHTML =
          "<td>" + escapeHtml(when) + "</td>" +
          "<td>" + (f.side === "buy"
            ? '<span class="up-text">BUY</span>'
            : '<span class="down-text">SELL</span>') + "</td>" +
          "<td>" + escapeHtml(String(f.symbol).replace(/^US\./, "")) + "</td>" +
          '<td class="num">' + f.quantity + "</td>" +
          '<td class="num">' + money(f.price) + "</td>" +
          '<td class="num">' + money(f.cash_after) + "</td>" +
          '<td class="num">' + (f.realised === null ? "—" : signed(f.realised)) + "</td>";
        fills.appendChild(tr);
      });
    }
  }

  function loadAccount() {
    return fetch("/api/paper/account", { headers: { Accept: "application/json" } })
      .then(function (r) { if (!r.ok) throw new Error("account " + r.status); return r.json(); })
      .then(renderAccount)
      .catch(function (e) {
        $("paper-conn").textContent = "unavailable";
        $("paper-conn").style.cssText = "background:#fef2f2;color:#991b1b";
        alertBox("Could not load the paper account: " + e.message, "error");
      });
  }

  // ------------------------------------------------------------------ quote

  function refreshQuote() {
    var symbol = $("symbol").value.trim().toUpperCase();
    if (!symbol) return;
    if (symbol.indexOf(".") === -1) {
      symbol = "US." + symbol;
      $("symbol").value = symbol;
    }
    $("quote-line").textContent = "Reading the price…";
    fetch("/api/paper/quote?symbol=" + encodeURIComponent(symbol), { headers: { Accept: "application/json" } })
      .then(function (r) {
        if (!r.ok) return r.json().then(function (b) { throw new Error(b.detail || "no quote"); });
        return r.json();
      })
      .then(function (q) {
        lastQuote = q;
        $("quote-line").innerHTML =
          "<strong>" + escapeHtml(q.symbol.replace(/^US\./, "")) + "</strong> · " +
          escapeHtml(q.name || "") + " · <strong>" + money(q.last_price) + "</strong> (" +
          (Number(q.change_rate) >= 0 ? "+" : "") + Number(q.change_rate).toFixed(2) + "%)";
        updateEstimate();
      })
      .catch(function (e) {
        lastQuote = null;
        $("quote-line").textContent = e.message;
        updateEstimate();
      });
  }

  function updateEstimate() {
    var qty = parseInt($("qty").value, 10);
    if (!lastQuote || !qty || qty < 1) { $("estimate").textContent = ""; return; }
    var value = qty * Number(lastQuote.last_price);
    $("estimate").textContent =
      qty + " × " + money(lastQuote.last_price) + " = " + money(value) +
      " — filled at that price if the broker still quotes it.";
  }

  // ------------------------------------------------------------------ order

  function submitOrder(side) {
    if (busy) return;
    var symbol = $("symbol").value.trim().toUpperCase();
    var qty = parseInt($("qty").value, 10);
    if (!symbol) { alertBox("Enter a symbol first, for example US.AAPL.", "error"); return; }
    if (!qty || qty < 1) { alertBox("Quantity must be at least 1 share.", "error"); return; }

    busy = true;
    $("buy-btn").disabled = true;
    $("sell-btn").disabled = true;
    fetch("/api/paper/order", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ symbol: symbol, side: side, quantity: qty })
    })
      .then(function (r) {
        return r.json().then(function (body) { return { ok: r.ok, status: r.status, body: body }; });
      })
      .then(function (result) {
        if (!result.ok) {
          throw new Error(result.body.detail || ("order failed (" + result.status + ")"));
        }
        var fill = result.body.fill;
        renderAccount(result.body.account);
        alertBox(
          (fill.side === "buy" ? "Bought " : "Sold ") + fill.quantity + " " +
          fill.symbol.replace(/^US\./, "") + " at " + money(fill.price) +
          (fill.realised === null ? "" : " · realised " + money(fill.realised)),
          "ok"
        );
      })
      .catch(function (e) { alertBox(e.message, "error"); })
      .finally(function () {
        busy = false;
        $("buy-btn").disabled = false;
        $("sell-btn").disabled = false;
      });
  }

  // ------------------------------------------------------------------- init

  document.addEventListener("DOMContentLoaded", function () {
    $("buy-btn").addEventListener("click", function (event) {
      event.preventDefault();
      submitOrder("buy");
    });
    $("sell-btn").addEventListener("click", function (event) {
      event.preventDefault();
      submitOrder("sell");
    });
    $("order-form").addEventListener("submit", function (event) { event.preventDefault(); });

    var timer = null;
    $("symbol").addEventListener("input", function () {
      clearTimeout(timer);
      timer = setTimeout(refreshQuote, 350);
    });
    $("symbol").addEventListener("change", refreshQuote);
    $("qty").addEventListener("input", updateEstimate);

    $("paper-reset").addEventListener("click", function () {
      if (!window.confirm("Reset the paper account to its starting cash?")) return;
      fetch("/api/paper/reset", { method: "POST", headers: { Accept: "application/json" } })
        .then(function (r) { return r.json(); })
        .then(function (body) { renderAccount(body.account); alertBox("Account reset.", "ok"); })
        .catch(function (e) { alertBox("Reset failed: " + e.message, "error"); });
    });

    // Symbol suggestions: the same 100 names the dashboard lists.
    fetch("/api/public/us/market?size=500", { headers: { Accept: "application/json" } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data || !data.rows) return;
        var list = $("symbols");
        data.rows.forEach(function (row) {
          var option = document.createElement("option");
          option.value = row.symbol;
          option.label = row.name;
          list.appendChild(option);
        });
      })
      .catch(function () { /* suggestions are a convenience, not required */ });

    loadAccount()
      .then(function () {
        $("paper-conn").textContent = "simulated";
        $("paper-conn").style.cssText = "background:#fef3c7;color:#92400e";
        // A hosted demo with no broker loads demo/paper_seed.json: say so.
        return fetch("/api/journal/summary", { headers: { Accept: "application/json" } })
          .then(function (r) { return r.ok ? r.json() : null; })
          .then(function (summary) {
            if (summary && summary.seeded) {
              $("paper-conn").textContent = "sample account";
              var banner = document.querySelector(".alert-sim");
              if (banner) {
                banner.innerHTML = '<strong>Sample account.</strong> This hosted copy has no ' +
                  'broker connection, so it starts from a shipped set of trades at real ' +
                  'historical prices. Orders you place here are still simulated and still stored ' +
                  'on this server — <strong>nothing reaches a broker</strong>.';
              }
            }
          })
          .catch(function () { /* the banner is a nicety, not a requirement */ });
      });

    setInterval(loadAccount, 30000);
  });
})();
