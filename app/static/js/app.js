/* TechIS app.js — theme + motion.
   Dependency policy: GSAP (official CDN) is OPTIONAL. Every feature here
   degrades gracefully when GSAP is missing — content is never hidden. */
(function () {
  "use strict";

  var reduceMotion = window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ---------- Theme switch (persists via localStorage) ---------- */
  function currentTheme() {
    return document.documentElement.getAttribute("data-theme") || "dark";
  }
  function applyTheme(t) {
    document.documentElement.setAttribute("data-theme", t);
    try { localStorage.setItem("tt-theme", t); } catch (e) { /* private mode */ }
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", t === "light" ? "#f2f5fb" : "#0a1428");
    var label = document.querySelector("[data-theme-label]");
    if (label) label.textContent = t === "light" ? "Light theme" : "Dark theme";
  }
  document.querySelectorAll("[data-theme-toggle]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      applyTheme(currentTheme() === "light" ? "dark" : "light");
    });
  });
  applyTheme(currentTheme());

  /* ---------- Animated KPI counters (actual values only) ---------- */
  function animateCount(el) {
    var target = parseFloat(el.getAttribute("data-count"));
    if (isNaN(target)) return;
    var isPercent = el.getAttribute("data-count-suffix") === "%";
    var finalText = isPercent ? target.toFixed(target % 1 ? 1 : 0) + "%" : String(target);
    if (reduceMotion || !window.gsap) { el.textContent = finalText; return; }
    var obj = { v: 0 };
    window.gsap.to(obj, {
      v: target, duration: 1.1, ease: "power2.out",
      onUpdate: function () {
        el.textContent = isPercent
          ? (Math.round(obj.v * 10) / 10).toFixed(obj.v % 1 ? 1 : 0) + "%"
          : Math.round(obj.v);
      },
      onComplete: function () { el.textContent = finalText; }
    });
  }

  /* ---------- Password show/hide toggle (auth forms) ---------- */
  document.querySelectorAll(".btn-toggle-pw").forEach(function (btn) {
    var targetId = btn.getAttribute("aria-controls");
    var target = targetId ? document.getElementById(targetId) : null;
    if (!target) return;
    btn.addEventListener("click", function () {
      var showing = target.type === "text";
      target.type = showing ? "password" : "text";
      btn.setAttribute("aria-pressed", showing ? "false" : "true");
      btn.textContent = showing ? "&#128065;" : "&#128066;";
    });
  });

  /* ---------- Cinematic page motion (GSAP only; skip if absent) ---------- */
  function initMotion() {
    var counters = document.querySelectorAll("[data-count]");
    counters.forEach(function (el) {
      // Set final text immediately as fallback; animate only if GSAP is present.
      animateCount(el);
    });

    if (!window.gsap || reduceMotion) return;

    // Staggered entrance for key elements inside the content wrapper.
    var wrapper = document.querySelector("[data-stagger]");
    if (wrapper && wrapper.children.length) {
      window.gsap.from(wrapper.children, {
        y: 18, opacity: 0, duration: 0.55, stagger: 0.07,
        ease: "power3.out", clearProps: "all"
      });
    }
    // Sidebar entrance.
    var sidebar = document.querySelector(".sidebar");
    if (sidebar) {
      window.gsap.from(sidebar, { x: -28, opacity: 0, duration: 0.5, ease: "power3.out", clearProps: "all" });
    }
    // Auth hero (login/register).
    var hero = document.querySelector(".auth-hero");
    if (hero) {
      window.gsap.from(hero.children, { y: 22, opacity: 0, duration: 0.6, stagger: 0.09, ease: "power3.out", clearProps: "all" });
    }
    // Subtle chart/KPI reveal.
    document.querySelectorAll(".kpi-card").forEach(function (card, i) {
      window.gsap.from(card, { y: 24, opacity: 0, duration: 0.5, delay: 0.08 * i, ease: "power3.out", clearProps: "all" });
    });
    // Animated background geometric shapes on login.
    document.querySelectorAll(".aurora-geo").forEach(function (g, i) {
      window.gsap.to(g, { rotation: i % 2 ? "+=14" : "-=14", duration: 8 + i * 2, yoyo: true, repeat: -1, ease: "sine.inOut" });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initMotion);
  } else {
    initMotion();
  }
})();
