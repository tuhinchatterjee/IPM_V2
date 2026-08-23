/*
 * Keep the suggestion chips clickable.
 *
 * The prompt-suggestions popup is only shown while the chat input has focus
 * (`.chat-input-wrap:focus-within`). Browsers fire `mousedown` -> blur -> `click`,
 * so pressing a chip blurs the input, which hides the popup and cancels the click
 * before it ever reaches the chip — the chip appears to do nothing.
 *
 * Suppressing the default action of `mousedown` inside the popup stops the focus
 * from moving, so the input stays focused, the popup stays up, and the click
 * completes normally. Capture phase so this runs before React's own handlers.
 *
 * This is why the popup can safely keep `pointer-events: none` while hidden (which
 * is what stops it swallowing clicks on the panel behind it): the two rules only
 * work together with this guard in place.
 */
(function () {
  "use strict";

  document.addEventListener(
    "mousedown",
    function (event) {
      var target = event.target;
      if (target && target.closest && target.closest(".chat-suggestions-popup")) {
        event.preventDefault();
      }
    },
    true
  );
})();
