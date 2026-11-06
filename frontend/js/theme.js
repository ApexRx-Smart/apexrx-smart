/* Light and dark mode. Loaded in <head> so the page never flashes the wrong theme.
 * The choice is kept per browser; with no choice the device setting is followed. */
(function () {
  'use strict';
  var KEY = 'apexrx_theme';
  var root = document.documentElement;
  var media = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;

  function saved() { try { return localStorage.getItem(KEY); } catch (e) { return null; } }
  function device() { return media && media.matches ? 'dark' : 'light'; }
  function apply(theme) {
    root.dataset.theme = theme;
    root.style.colorScheme = theme;
    window.dispatchEvent(new CustomEvent('apexrx:theme', { detail: theme }));
  }

  apply(saved() === 'dark' || saved() === 'light' ? saved() : device());
  if (media && media.addEventListener) {
    media.addEventListener('change', function () { if (!saved()) apply(device()); });
  }

  window.ApexTheme = {
    get: function () { return root.dataset.theme; },
    toggle: function () {
      var next = root.dataset.theme === 'dark' ? 'light' : 'dark';
      try { localStorage.setItem(KEY, next); } catch (e) { /* private mode: lasts for this page */ }
      apply(next);
      return next;
    }
  };
})();
