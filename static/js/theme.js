/**
 * theme.js — Light/dark theme with three modes: "light", "dark", "auto"
 * (auto follows the OS/browser prefers-color-scheme). Applies via
 * Bootstrap 5.3's data-bs-theme attribute on <html>.
 *
 * Loaded as the first thing in <head>, without defer, so the theme is set
 * before the page paints (no flash of the wrong theme). The dropdown wiring
 * at the bottom waits for the navbar to exist.
 */
(function () {
    "use strict";

    var STORAGE_KEY = "fair_theme"; // "light" | "dark" | "auto"
    var media = window.matchMedia("(prefers-color-scheme: dark)");

    function getChoice() {
        try {
            var stored = localStorage.getItem(STORAGE_KEY);
            return stored === "light" || stored === "dark" ? stored : "auto";
        } catch (e) {
            return "auto";
        }
    }

    function effectiveTheme(choice) {
        return choice === "light" || choice === "dark" ? choice : (media.matches ? "dark" : "light");
    }

    function apply(choice) {
        document.documentElement.setAttribute("data-bs-theme", effectiveTheme(choice));
    }

    // Apply immediately, before first paint.
    apply(getChoice());

    // Follow OS-level changes live while "auto" is selected.
    media.addEventListener("change", function () {
        if (getChoice() === "auto") apply("auto");
        updateUI();
    });

    function setTheme(choice) {
        try {
            if (choice === "auto") localStorage.removeItem(STORAGE_KEY);
            else localStorage.setItem(STORAGE_KEY, choice);
        } catch (e) { /* private mode / storage blocked: theme just won't persist */ }
        apply(choice);
        updateUI();
    }

    function updateUI() {
        var choice = getChoice();
        var icon = document.getElementById("themeIcon");
        if (icon) icon.textContent = choice === "light" ? "☀️" : choice === "dark" ? "🌙" : "🖥️";
        var buttons = document.querySelectorAll("[data-theme-choice]");
        for (var i = 0; i < buttons.length; i++) {
            buttons[i].classList.toggle("active", buttons[i].getAttribute("data-theme-choice") === choice);
        }
    }

    function init() {
        var buttons = document.querySelectorAll("[data-theme-choice]");
        for (var i = 0; i < buttons.length; i++) {
            buttons[i].addEventListener("click", function () {
                setTheme(this.getAttribute("data-theme-choice"));
            });
        }
        updateUI();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
