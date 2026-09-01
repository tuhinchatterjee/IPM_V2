/*
 * Global busy indicator.
 *
 * Several actions in this tool are genuinely slow — generating a committee pack
 * renders seven matplotlib charts and assembles a 15-page document, which takes
 * the better part of ten seconds. Without feedback the button looks dead and the
 * natural response is to click it again.
 *
 * Dash 4.3 issues every callback through `fetch` to /_dash-update-component
 * (verified — it uses no XMLHttpRequest at all), so counting in-flight requests
 * to that endpoint gives an accurate global busy state that covers downloads,
 * tab switches and navigation alike, with no per-callback wiring.
 *
 * Three signals, in increasing order of subtlety:
 *   1. a progress bar across the top of the window,
 *   2. a spinner on the control that was clicked,
 *   3. a gentle pulse on the region Dash is replacing (Dash sets
 *      data-dash-is-loading on it for us).
 *
 * Nothing here disables a control or sets pointer-events. A previous fix in this
 * codebase was undone by exactly that: suppressing pointer events on a live
 * element swallowed the click it was meant to be reporting on.
 */
(function () {
  "use strict";

  // Below this, a spinner reads as a flicker rather than as feedback.
  var SHOW_AFTER_MS = 140;
  // If a request never settles, do not leave the page looking stuck forever.
  var FAILSAFE_MS = 60000;
  // A click is credited with starting a request only if one begins soon after.
  // Generous, because one click often fires a chain of callbacks: selecting a
  // report type runs a fast store update and then a slow re-render, and the
  // spinner belongs to the card for the whole chain, not just the first hop.
  var CLICK_WINDOW_MS = 3000;

  var BUSY_CLASS = "ipm-busy";
  var BUTTON_CLASS = "ipm-btn-busy";

  var CLICKABLE = [
    "button",
    ".rep-type-card",
    ".rep-fmt-card",
    ".subnav-item",
    ".ipm-nav-item",
    ".matrix-row",
    ".obligor-card",
    ".chat-send",
  ].join(",");

  var inflight = 0;
  var showTimer = null;
  var failsafeTimer = null;
  var rafId = null;
  var bar = null;
  var fill = null;
  var width = 0;
  var visible = false;
  var lastClicked = null;
  var lastClickedAt = 0;

  function ensureBar() {
    if (bar || !document.body) {
      return bar;
    }
    bar = document.createElement("div");
    bar.className = "ipm-progress";
    fill = document.createElement("div");
    fill.className = "ipm-progress-fill";
    bar.appendChild(fill);
    document.body.appendChild(bar);
    return bar;
  }

  function step() {
    rafId = null;
    if (!visible) {
      return;
    }
    // Ease toward 90% and wait there: the remaining 10% belongs to the response,
    // so the bar never claims to be finished before the work is.
    width += (90 - width) * 0.035;
    if (fill) {
      fill.style.width = width.toFixed(2) + "%";
    }
    rafId = window.requestAnimationFrame(step);
  }

  function show() {
    if (visible || !ensureBar()) {
      return;
    }
    visible = true;
    width = 8;
    bar.classList.remove("is-done");
    bar.classList.add("is-active");
    fill.style.width = "8%";
    document.documentElement.classList.add(BUSY_CLASS);
    markClickedBusy();
    rafId = window.requestAnimationFrame(step);
  }

  function hide() {
    if (showTimer) {
      window.clearTimeout(showTimer);
      showTimer = null;
    }
    document.documentElement.classList.remove(BUSY_CLASS);
    clearClickedBusy();
    if (!visible) {
      return;
    }
    visible = false;
    if (rafId) {
      window.cancelAnimationFrame(rafId);
      rafId = null;
    }
    // Run to 100% before fading, so the bar resolves rather than vanishing.
    fill.style.width = "100%";
    bar.classList.add("is-done");
    window.setTimeout(function () {
      if (!visible && bar) {
        bar.classList.remove("is-active", "is-done");
        fill.style.width = "0%";
      }
    }, 260);
  }

  function markClickedBusy() {
    if (!lastClicked || Date.now() - lastClickedAt > CLICK_WINDOW_MS) {
      return;
    }
    if (lastClicked.isConnected) {
      lastClicked.classList.add(BUTTON_CLASS);
    }
  }

  function clearClickedBusy() {
    if (lastClicked && lastClicked.classList) {
      lastClicked.classList.remove(BUTTON_CLASS);
    }
    // The reference is deliberately kept. A fast callback settling between two
    // hops of the same chain would otherwise drop it, and the slow hop that
    // follows would have nothing to put the spinner on. CLICK_WINDOW_MS is what
    // decides when a click has gone stale.
  }

  function start() {
    inflight += 1;
    if (inflight === 1) {
      showTimer = window.setTimeout(show, SHOW_AFTER_MS);
      failsafeTimer = window.setTimeout(function () {
        inflight = 0;
        hide();
      }, FAILSAFE_MS);
    }
  }

  function end() {
    inflight = Math.max(0, inflight - 1);
    if (inflight === 0) {
      if (failsafeTimer) {
        window.clearTimeout(failsafeTimer);
        failsafeTimer = null;
      }
      hide();
    }
  }

  document.addEventListener(
    "click",
    function (event) {
      var target = event.target;
      if (!target || !target.closest) {
        return;
      }
      var el = target.closest(CLICKABLE);
      if (el) {
        lastClicked = el;
        lastClickedAt = Date.now();
        // A request already in flight is this click's; mark it immediately.
        if (visible) {
          markClickedBusy();
        }
      }
    },
    true
  );

  function isCallback(url) {
    return typeof url === "string" && url.indexOf("_dash-update-component") !== -1;
  }

  var originalFetch = window.fetch;
  if (typeof originalFetch === "function") {
    window.fetch = function (input) {
      var url = typeof input === "string" ? input : (input && input.url) || "";
      if (!isCallback(url)) {
        return originalFetch.apply(this, arguments);
      }
      start();
      var settled = false;
      var done = function () {
        if (!settled) {
          settled = true;
          end();
        }
      };
      var promise;
      try {
        promise = originalFetch.apply(this, arguments);
      } catch (err) {
        done();
        throw err;
      }
      return promise.then(
        function (response) {
          done();
          return response;
        },
        function (err) {
          done();
          throw err;
        }
      );
    };
  }
})();
