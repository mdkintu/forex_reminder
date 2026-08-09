/**
 * clock.js — Live inactivity countdown for forex trading accounts.
 *
 * Two supported markup modes:
 *
 * 1. Full clock (detail page):
 *    <div class="clock" data-deadline="2025-09-01T10:00:00+00:00"
 *         data-full="true">
 *      <span class="clock-unit"><b data-role="days">--</b><i>Days</i></span>
 *      <span class="clock-sep">:</span>
 *      <span class="clock-unit"><b data-role="hours">--</b><i>Hours</i></span>
 *      <span class="clock-sep">:</span>
 *      <span class="clock-unit"><b data-role="minutes">--</b><i>Min</i></span>
 *      <span class="clock-sep">:</span>
 *      <span class="clock-unit"><b data-role="seconds">--</b><i>Sec</i></span>
 *      <p class="clock-status" data-role="status"></p>
 *    </div>
 *
 * 2. Badge (list page) — many per page:
 *    <span class="clock-badge" data-deadline="2025-09-01T10:00:00+00:00"
 *          data-label="days left">…</span>
 */
(function () {
    "use strict";

    var MS_PER_DAY = 24 * 60 * 60 * 1000;
    var MS_PER_HOUR = 60 * 60 * 1000;
    var MS_PER_MIN = 60 * 1000;

    function pad(n) {
        return String(n).padStart(2, "0");
    }

    function updateFullClock(root) {
        var deadline = new Date(root.dataset.deadline).getTime();
        var statusEl = root.querySelector('[data-role="status"]');
        var diff = deadline - Date.now();

        if (diff <= 0) {
            root.classList.add("is-expired");
            setText(root, "days", "00");
            setText(root, "hours", "00");
            setText(root, "minutes", "00");
            setText(root, "seconds", "00");
            if (statusEl) {
                statusEl.textContent = "Account may be closed";
                statusEl.classList.add("status-danger");
            }
            return;
        }

        var days = Math.floor(diff / MS_PER_DAY);
        var hours = Math.floor((diff % MS_PER_DAY) / MS_PER_HOUR);
        var minutes = Math.floor((diff % MS_PER_HOUR) / MS_PER_MIN);
        var seconds = Math.floor((diff % MS_PER_MIN) / 1000);

        setText(root, "days", pad(days));
        setText(root, "hours", pad(hours));
        setText(root, "minutes", pad(minutes));
        setText(root, "seconds", pad(seconds));

        if (statusEl) {
            // Urgency indicator
            var daysLeft = diff / MS_PER_DAY;
            root.classList.remove("is-warning", "is-critical");
            if (daysLeft <= 3) {
                root.classList.add("is-critical");
                statusEl.textContent = "Critical — closing soon";
            } else if (daysLeft <= 7) {
                root.classList.add("is-warning");
                statusEl.textContent = "Getting close — plan a trade";
            } else {
                statusEl.textContent = "Active";
            }
        }
    }

    function updateBadge(badge) {
        var deadline = new Date(badge.dataset.deadline).getTime();
        var diff = deadline - Date.now();
        var label = badge.dataset.label || "days left";

        if (diff <= 0) {
            badge.textContent = "Inactive";
            badge.classList.remove("badge-has-days");
            badge.classList.add("badge-expired");
            return;
        }

        var days = Math.ceil(diff / MS_PER_DAY);
        badge.textContent = days + " " + label;
        if (!badge.classList.contains("badge-has-days")) {
            badge.classList.add("badge-has-days");
        }
        // Update urgency color based on remaining days
        badge.classList.remove("badge-critical", "badge-warning", "badge-ok");
        if (days <= 3) {
            badge.classList.add("badge-critical");
        } else if (days <= 7) {
            badge.classList.add("badge-warning");
        } else {
            badge.classList.add("badge-ok");
        }
    }

    function setText(root, role, text) {
        var el = root.querySelector('[data-role="' + role + '"]');
        if (el) el.textContent = text;
    }

    function init() {
        // Full clocks
        var clocks = document.querySelectorAll(".clock[data-deadline]");
        clocks.forEach(function (clock) {
            updateFullClock(clock);
            setInterval(function () { updateFullClock(clock); }, 1000);
        });

        // Badges
        var badges = document.querySelectorAll(".clock-badge[data-deadline]");
        badges.forEach(function (badge) {
            updateBadge(badge);
            setInterval(function () { updateBadge(badge); }, 1000);
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
