'use strict';
/* Adds a show/hide button to every password field, including fields drawn later. */
(function () {
  const TEXT = {
    en: ['Show password', 'Hide password'],
    fr: ['Afficher le mot de passe', 'Masquer le mot de passe'],
    rw: ['Erekana ijambobanga', 'Hisha ijambobanga']
  };
  const EYE = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/></svg>';
  const EYE_OFF = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 3l18 18"/><path d="M10.6 5.1A10.6 10.6 0 0 1 12 5c6.4 0 10 7 10 7a17 17 0 0 1-3.2 4.1M6.5 6.6A17 17 0 0 0 2 12s3.6 7 10 7a10.6 10.6 0 0 0 5.4-1.5"/><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2"/></svg>';
  const words = () => TEXT[document.documentElement.lang] || TEXT.en;

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
    button.addEventListener('click', () => {
      input.type = input.type === 'password' ? 'text' : 'password';
      paint(button, input); input.focus();
    });
  }
  const scan = () => document.querySelectorAll('input[type=password]').forEach(enhance);
  new MutationObserver(scan).observe(document.documentElement, { childList: true, subtree: true });
  scan();
})();
