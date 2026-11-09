'use strict';
/* Show/hide button for every password field, including fields added later.
 *
 * Taken from the feature/dashboards-and-registration branch (2dd95a9), with two
 * changes: activating the button from the keyboard keeps focus on the button,
 * and every field goes back to hidden when its form is submitted, so a
 * password is never left visible (or offered to the browser as plain text).
 * The value itself is never read, copied or stored.
 */
(function () {
  const TEXT = {
    en: ['Show password', 'Hide password'],
    fr: ['Afficher le mot de passe', 'Masquer le mot de passe'],
    rw: ['Erekana ijambobanga', 'Hisha ijambobanga']
  };
  const EYE = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/></svg>';
  const EYE_OFF = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 3l18 18"/><path d="M10.6 5.1A10.6 10.6 0 0 1 12 5c6.4 0 10 7 10 7a17 17 0 0 1-3.2 4.1M6.5 6.6A17 17 0 0 0 2 12s3.6 7 10 7a10.6 10.6 0 0 0 5.4-1.5"/><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2"/></svg>';
  const words = () => TEXT[(document.documentElement.lang || 'en').slice(0, 2)] || TEXT.en;

  function paint(button, input) {
    const shown = input.type === 'text';
    button.innerHTML = shown ? EYE_OFF : EYE;
    button.setAttribute('aria-label', words()[shown ? 1 : 0]);
    button.title = words()[shown ? 1 : 0];
    button.setAttribute('aria-pressed', String(shown));
  }
  function enhance(input) {
    if (input.dataset.toggle) return;
    input.dataset.toggle = 'on';
    const wrap = document.createElement('span'); wrap.className = 'pw-wrap';
    input.replaceWith(wrap); wrap.append(input);
    const button = document.createElement('button');
    button.type = 'button'; button.className = 'pw-eye';
    paint(button, input); wrap.append(button);
    button.addEventListener('click', e => {
      input.type = input.type === 'password' ? 'text' : 'password';
      paint(button, input);
      // Mouse or touch: back to typing. Keyboard (detail 0): stay on the button.
      if (e.detail !== 0) input.focus();
    });
    if (input.form && !input.form.dataset.pwReset) {
      input.form.dataset.pwReset = 'on';
      input.form.addEventListener('submit', () => hideAll(input.form), true);
    }
  }
  function hideAll(root) {
    root.querySelectorAll('input[data-toggle]').forEach(input => {
      if (input.type !== 'text') return;
      input.type = 'password';
      const button = input.parentElement.querySelector('.pw-eye');
      if (button) paint(button, input);
    });
  }
  const scan = () => document.querySelectorAll('input[type=password]').forEach(enhance);
  new MutationObserver(scan).observe(document.documentElement, { childList: true, subtree: true });
  scan();
  window.ApexPasswordToggle = { hideAll: () => hideAll(document) };
})();
