/* Sign-in page: email, then the passcode, on one screen.

   State comes from the server (`window.__signin`): `started` means a session already
   exists and only the passcode is outstanding, `dev` shows the development-mode notice.
   Everything degrades to a plain form if this script fails to load. */
(function () {
  "use strict";

  var cfg = window.__signin || { started: false, dev: false };
  var $ = function (id) { return document.getElementById(id); };

  var alertBox = $("alert");
  var emailForm = $("email-form");
  var codePanel = $("code-panel");
  var codeForm = $("code-form");
  var codeInput = $("code");
  var codeButton = $("code-submit");
  var emailButton = $("email-submit");
  var sentNote = $("sent-note");
  var sentAddress = $("sent-address");
  var devBanner = $("dev-banner");
  var setupLine = $("setup-line");
  var setupKey = $("setup-key");
  var stepEmail = $("step-email");
  var stepCode = $("step-code");

  function showAlert(message) {
    alertBox.textContent = message;
    alertBox.hidden = false;
  }

  function clearAlert() {
    alertBox.hidden = true;
    alertBox.textContent = "";
  }

  function toCodeStep(email, devSession) {
    emailForm.hidden = true;
    codePanel.hidden = false;
    stepEmail.classList.remove("active");
    stepCode.classList.add("active");
    if (email) sentAddress.textContent = email;
    // In development no mail is sent, so "check your inbox" would be a lie.
    sentNote.hidden = !!devSession;
    devBanner.hidden = !cfg.dev;
    codeInput.focus();
  }

  if (cfg.demo) {
    var demoForm = $("demo-form");
    if (demoForm) demoForm.hidden = false;
  }

  if (cfg.started) {
    toCodeStep(null, true);
    devBanner.hidden = !cfg.dev;
    if (cfg.setupKey) {
      setupKey.textContent = cfg.setupKey;
      setupLine.hidden = false;
    }
  } else if (cfg.dev) {
    devBanner.hidden = false;
  }

  emailForm.addEventListener("submit", async function (event) {
    event.preventDefault();
    clearAlert();
    var email = $("email").value.trim();
    if (!email || email.indexOf("@") < 1) {
      showAlert("Enter a valid email address.");
      return;
    }
    emailButton.disabled = true;
    emailButton.textContent = "Sending…";
    try {
      var response = await fetch("/auth/magic-link", {
        method: "POST",
        body: new URLSearchParams({ email: email }),
      });
      var body = {};
      try { body = await response.json(); } catch (ignored) {}
      if (response.status === 202) {
        if (body.dev_mode) {
          // Development: the server has already opened a half-session and only the
          // passcode is missing. Reload so it can render step 2 with the setup key —
          // no credential travels in the JSON.
          window.location.reload();
        } else {
          toCodeStep(email, false);
        }
      } else if (response.status === 429) {
        showAlert("Too many attempts. Wait a minute, then try again.");
      } else {
        showAlert(body.detail || "That address was refused. Check it and try again.");
      }
    } catch (error) {
      showAlert("Could not reach the server. Is it still running?");
    } finally {
      emailButton.disabled = false;
      emailButton.textContent = "Continue";
    }
  });

  codeInput.addEventListener("input", function () {
    codeInput.value = codeInput.value.replace(/\D/g, "").slice(0, 6);
  });

  codeForm.addEventListener("submit", async function (event) {
    event.preventDefault();
    clearAlert();
    var code = codeInput.value.trim();
    if (!/^\d{6}$/.test(code)) {
      showAlert("The code is six digits.");
      return;
    }
    codeButton.disabled = true;
    codeButton.textContent = "Verifying…";
    try {
      var response = await fetch("/auth/2fa", {
        method: "POST",
        body: new URLSearchParams({ code: code }),
        redirect: "follow",
      });
      if (response.ok) {
        // No session yet (the emailed link has not been opened) lands back on /sign-in.
        if (response.url && response.url.indexOf("/sign-in") !== -1) {
          showAlert("Open the sign-in link from your inbox first, then enter the code.");
        } else {
          window.location.href = "/app";
        }
        return;
      }
      var body = {};
      try { body = await response.json(); } catch (ignored) {}
      if (response.status === 429) {
        var wait = response.headers.get("Retry-After") || "a few";
        showAlert("Too many attempts. Wait " + wait + " seconds, then try again.");
      } else if (response.status === 401) {
        showAlert("That code is not valid. Check your authenticator app and try again.");
      } else {
        showAlert(body.detail || "Could not verify that code.");
      }
    } catch (error) {
      showAlert("Could not reach the server.");
    } finally {
      codeButton.disabled = false;
      codeButton.textContent = "Verify and sign in";
    }
  });

  $("back").addEventListener("click", function () {
    codePanel.hidden = true;
    emailForm.hidden = false;
    stepCode.classList.remove("active");
    stepEmail.classList.add("active");
    codeInput.value = "";
    clearAlert();
    $("email").focus();
  });
})();
