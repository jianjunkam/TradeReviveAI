/* Diagnosis chat: a page that is only the conversation.

   The Flowise widget is gone. It rendered an iframe of the hosted chat page, which sends
   X-Frame-Options: SAMEORIGIN, so it always collapsed to a floating bubble over a page of
   buttons that did nothing. Here the page owns the transcript and the composer, and the
   server proxies the question — no iframe, no CORS, no dead buttons. */

(function () {
  "use strict";

  var log = document.getElementById("chat-log");
  var form = document.getElementById("chat-form");
  var input = document.getElementById("chat-input");
  var send = document.getElementById("chat-send");
  var status = document.getElementById("chat-status");
  var newChat = document.getElementById("chat-new");

  var SESSION_KEY = "diagnosis-session";
  var busy = false;

  function sessionId() {
    var id = window.localStorage.getItem(SESSION_KEY);
    if (!id) {
      id = "diag-" + Math.random().toString(36).slice(2) + Date.now().toString(36);
      window.localStorage.setItem(SESSION_KEY, id);
    }
    return id;
  }

  function setStatus(text, kind) {
    status.textContent = text;
    if (kind === "error") {
      status.style.background = "#fef2f2";
      status.style.color = "#991b1b";
    } else if (kind === "busy") {
      status.style.background = "#f1f5f9";
      status.style.color = "#475569";
    } else {
      status.style.background = "#ecfdf5";
      status.style.color = "#047857";
    }
  }

  // Answers arrive with light markdown (bold, rules, numbered lists). Render that, and
  // nothing else: the text is escaped first, so an answer can never inject markup.
  function renderMarkdown(text) {
    var escaped = String(text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");

    var out = [];
    var list = null;

    function closeList() {
      if (list) { out.push("</" + list + ">"); list = null; }
    }

    escaped.split(/\r?\n/).forEach(function (line) {
      var trimmed = line.trim();

      if (!trimmed) {
        // A blank line between list items must not restart the list, or every item is "1.".
        if (list) return;
        out.push("<p></p>");
        return;
      }
      if (/^-{3,}$/.test(trimmed)) { closeList(); out.push("<hr>"); return; }

      // Models often restart at "1." for every item, bolded or not. The <ol> supplies the
      // real numbering, so the label is stripped rather than printed twice.
      var ordered = /^\*\*\d+[.)]\*\*/.test(trimmed) || /^\d+[.)]\s+/.test(trimmed);
      if (ordered) {
        trimmed = trimmed
          .replace(/^\*\*\d+[.)]\*\*\s*/, "")
          .replace(/^\d+[.)]\s+/, "");
      }

      var bullet = trimmed.match(/^[-*]\s+(.*)$/);
      var inline = trimmed
        .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
        .replace(/`([^`]+)`/g, "<code>$1</code>");

      if (ordered) {
        if (list !== "ol") { closeList(); out.push("<ol>"); list = "ol"; }
        out.push("<li>" + inline + "</li>");
        return;
      }
      if (bullet) {
        if (list !== "ul") { closeList(); out.push("<ul>"); list = "ul"; }
        out.push("<li>" + inline.replace(/^[-*]\s+/, "") + "</li>");
        return;
      }

      closeList();
      out.push("<p>" + inline + "</p>");
    });
    closeList();

    return out.join("");
  }

  function bubble(who, text) {
    var msg = document.createElement("div");
    msg.className = "chat-msg " + who;

    var body = document.createElement("div");
    body.className = "bubble";
    if (who === "bot") {
      body.innerHTML = renderMarkdown(text);
    } else {
      // What the reader typed is shown exactly as typed.
      body.textContent = text;
    }

    msg.appendChild(body);
    log.appendChild(msg);
    log.scrollTop = log.scrollHeight;
    return msg;
  }

  function typing() {
    var msg = document.createElement("div");
    msg.className = "chat-msg bot typing";
    var body = document.createElement("div");
    body.className = "bubble";
    body.innerHTML = '<span class="dot-pulse"></span><span class="dot-pulse"></span><span class="dot-pulse"></span>';
    msg.appendChild(body);
    log.appendChild(msg);
    log.scrollTop = log.scrollHeight;
    return msg;
  }

  function autosize() {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 160) + "px";
  }

  function ask(text) {
    if (busy) return;
    busy = true;
    send.disabled = true;
    setStatus("thinking…", "busy");

    bubble("user", text);
    var pending = typing();

    fetch("/api/diagnosis/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ message: text, session_id: sessionId() })
    })
      .then(function (response) {
        return response.json().then(function (body) {
          if (!response.ok) throw new Error(body.detail || ("HTTP " + response.status));
          return body;
        });
      })
      .then(function (body) {
        pending.remove();
        bubble("bot", body.text);
        setStatus("ready");
      })
      .catch(function (error) {
        pending.remove();
        bubble("bot error", "That did not work: " + error.message);
        setStatus("error", "error");
      })
      .then(function () {
        busy = false;
        send.disabled = false;
        input.focus();
      });
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    var text = input.value.trim();
    if (!text) return;
    input.value = "";
    autosize();
    ask(text);
  });

  input.addEventListener("keydown", function (event) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      form.requestSubmit();
    }
  });
  input.addEventListener("input", autosize);

  newChat.addEventListener("click", function () {
    window.localStorage.removeItem(SESSION_KEY);
    log.innerHTML = "";
    bubble("bot", "New conversation. What would you like to work through?");
    setStatus("ready");
    input.focus();
  });

  setStatus("ready");
  input.focus();
})();
