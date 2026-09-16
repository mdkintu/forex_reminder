/**
 * tz-detect.js — Auto-detect the signed-in user's browser timezone (once) so
 * "days since trade" is computed in their local calendar day, not UTC.
 *
 * Reads the IANA timezone off document.body.dataset.userTimezone (set by
 * base.html) and, if the server hasn't saved one yet, pings the current page
 * with ?tz=<zone> once per session so the server can store it.
 */
(function () {
    "use strict";

    var savedTz = document.body.dataset.userTimezone || "";

    var detected = (function () {
        try { return new Intl.DateTimeFormat().resolvedOptions().timeZone; }
        catch (e) { return null; }
    })();
    if (!detected) return;

    // Only bother if the server hasn't saved a timezone for this user yet.
    var hasTz = savedTz && savedTz !== "UTC";

    // Ping once per session so we don't loop. Use a flag in sessionStorage.
    if (!hasTz && !sessionStorage.getItem("tz_auto_detected")) {
        sessionStorage.setItem("tz_auto_detected", "1");
        fetch(location.pathname + location.search +
              (location.search ? "&tz=" : "?tz=") + encodeURIComponent(detected),
              { method: "GET", credentials: "same-origin" });
    }
})();
