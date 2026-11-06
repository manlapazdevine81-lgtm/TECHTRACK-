/* TECHTRACK landing page (Phase 10).
   - Mobile navigation toggle (aria-expanded driven)
   - Subtle reveal-on-scroll, only when the visitor allows motion
   - Clean geometric fallback if a photo fails to load (never a broken icon)
   No third-party dependencies; everything degrades to a static page. */
(function () {
  "use strict";

  var root = document.documentElement;
  root.classList.add("lp-js");

  var reduceMotion = window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ---------- Mobile menu ---------- */
  var toggle = document.querySelector("[data-lp-menu]");
  var menu = document.getElementById("lp-menu");
  if (toggle && menu) {
    var setOpen = function (open) {
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      toggle.setAttribute("aria-label", open ? "Close navigation menu" : "Open navigation menu");
      menu.classList.toggle("is-open", open);
    };
    toggle.addEventListener("click", function () {
      setOpen(toggle.getAttribute("aria-expanded") !== "true");
    });
    // Close after choosing a link, on Escape, and when the viewport grows.
    menu.addEventListener("click", function (e) {
      if (e.target.closest("a")) setOpen(false);
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && toggle.getAttribute("aria-expanded") === "true") {
        setOpen(false);
        toggle.focus();
      }
    });
    window.addEventListener("resize", function () {
      if (window.innerWidth > 760) setOpen(false);
    });
  }

  /* ---------- Entrance reveals ---------- */
  var targets = document.querySelectorAll(
    ".lp-hero-copy, .lp-collage, .lp-about-media, .lp-about-copy, .lp-feature, .lp-pv-card, .lp-campus"
  );

  if (reduceMotion || !("IntersectionObserver" in window)) {
    return; // content is visible by default — nothing to do
  }

  targets.forEach(function (el, i) {
    el.classList.add("lp-reveal");
    el.style.transitionDelay = (i % 4) * 70 + "ms";
  });

  var observer = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
      if (entry.isIntersecting) {
        entry.target.classList.add("is-visible");
        entry.target.style.transitionDelay = "";
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.12, rootMargin: "0px 0px -40px 0px" });

  targets.forEach(function (el) { observer.observe(el); });

  /* Safety net: an element taller than the viewport can never satisfy a
     12% threshold, so it would stay faded forever. Reveal such elements as
     soon as they are observed instead of waiting for a ratio they cannot meet. */
  targets.forEach(function (el) {
    if (el.getBoundingClientRect().height > window.innerHeight * 0.9) {
      el.classList.add("is-visible");
      observer.unobserve(el);
    }
  });
})();

/* ---------- Image fallback (runs even for reduced motion) ---------- */
document.addEventListener("DOMContentLoaded", function () {
  document.querySelectorAll(".lp img").forEach(function (img) {
    img.addEventListener("error", function () {
      img.style.visibility = "hidden";
      if (img.parentElement) img.parentElement.classList.add("lp-img-fallback");
    });
  });
});
