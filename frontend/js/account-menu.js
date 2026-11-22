'use strict';
/* Account menu: a small initials avatar that opens a menu with Sign out.
 * Shared by every signed-in workspace (patient reservations, pharmacy and
 * supplier dashboards, admin console), so sign-out looks and behaves the same
 * everywhere and always ends on the public landing page.
 *
 *   ApexAccountMenu.mount(host, {
 *     name, email,            // shown inside the menu (the account's own details only)
 *     detail,                 // optional second line, e.g. "Kigali Pharmacy · Manager"
 *     labels: { menu, signOut },
 *     onSignOut               // optional; default: ApexAccountMenu.signOut()
 *   }) -> { update(opts), close() }
 *   ApexAccountMenu.signOut()  // end this session (POST /auth/logout) and open index.html
 *
 * Keyboard: Enter, Space or ArrowDown opens it and focuses the first item;
 * Escape closes it and returns focus to the avatar; Tab out or a click outside
 * closes it. No profile pictures: initials only.
 */
(function (global) {
  const STYLE = `
.am{position:relative;display:inline-flex;align-items:center}
.am-btn{width:36px;height:36px;min-width:36px;border-radius:50%;border:1px solid rgba(127,140,160,.45);background:#0f1a3d;color:#fff;
  font:600 13px/1 Inter,system-ui,sans-serif;letter-spacing:.02em;display:grid;place-items:center;padding:0;cursor:pointer}
.am-btn:hover{box-shadow:0 0 0 3px rgba(26,148,88,.22)}
.am-btn:focus-visible{outline:3px solid #0da7de;outline-offset:2px}
.am-menu{position:absolute;right:0;top:calc(100% + 8px);z-index:1000;min-width:220px;max-width:min(300px,calc(100vw - 24px));
  background:#fff;color:#0f1a3d;border:1px solid rgba(15,26,61,.12);border-radius:12px;box-shadow:0 14px 34px rgba(5,10,30,.18);
  padding:6px;font:14px/1.4 Inter,system-ui,sans-serif;text-align:left}
.am-menu[hidden]{display:none}
.am-head{padding:8px 10px 10px;border-bottom:1px solid rgba(15,26,61,.1);margin-bottom:6px;display:flex;flex-direction:column;gap:2px;min-width:0}
.am-head strong{font-size:14px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.am-head span{font-size:12.5px;color:rgba(15,26,61,.64);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.am-item{display:flex;width:100%;align-items:center;gap:8px;border:0;background:none;color:inherit;text-align:left;
  padding:10px;border-radius:8px;font:inherit;cursor:pointer;min-height:40px}
.am-item:hover,.am-item:focus-visible{background:#eef4f1;outline:none}
:root[data-theme=dark] .am-menu{background:#142132;color:#e8eef4;border-color:#27394d}
:root[data-theme=dark] .am-head{border-color:#27394d}
:root[data-theme=dark] .am-head span{color:#9db0c2}
:root[data-theme=dark] .am-item:hover,:root[data-theme=dark] .am-item:focus-visible{background:#1a2a3e}`;

  function addStyle() {
    if (document.getElementById('am-style')) return;
    const s = document.createElement('style');
    s.id = 'am-style'; s.textContent = STYLE;
    document.head.appendChild(s);
  }

  function initials(name, email) {
    const words = String(name || '').trim().split(/\s+/).filter(w => /\p{L}|\d/u.test(w));
    if (words.length >= 2) return (words[0][0] + words[words.length - 1][0]).toUpperCase();
    if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
    const e = String(email || '').trim();
    return e ? e[0].toUpperCase() : '?';
  }

  function el(tag, attrs, text) {
    const n = document.createElement(tag);
    Object.entries(attrs || {}).forEach(([k, v]) => n.setAttribute(k, v));
    if (text != null) n.textContent = text;
    return n;
  }

  let seq = 0;
  function mount(host, opts) {
    addStyle();
    const id = 'am-menu-' + (++seq);
    const root = el('div', { class: 'am' });
    const btn = el('button', { type: 'button', class: 'am-btn', 'aria-haspopup': 'menu', 'aria-expanded': 'false', 'aria-controls': id });
    const ini = el('span', { 'aria-hidden': 'true' });
    btn.appendChild(ini);
    const menu = el('div', { class: 'am-menu', id, role: 'menu', hidden: '' });
    const head = el('div', { class: 'am-head', role: 'presentation' });
    const out = el('button', { type: 'button', class: 'am-item', role: 'menuitem', 'data-am': 'signout' });
    menu.append(head, out);
    root.append(btn, menu);
    host.replaceChildren(root);
    let current = {};

    function paint(o) {
      current = Object.assign({}, current, o);
      const labels = Object.assign({ menu: 'Account menu', signOut: 'Sign out' }, current.labels || {});
      ini.textContent = initials(current.name, current.email);
      btn.setAttribute('aria-label', labels.menu);
      btn.title = labels.menu;
      head.replaceChildren(...[current.name && el('strong', {}, current.name),
        current.email && current.email !== current.name && el('span', {}, current.email),
        current.detail && el('span', {}, current.detail)].filter(Boolean));
      head.hidden = !head.childElementCount;
      out.textContent = labels.signOut;
    }
    const items = () => Array.from(menu.querySelectorAll('[role=menuitem]'));
    function open(focusFirst) {
      menu.hidden = false; btn.setAttribute('aria-expanded', 'true');
      if (focusFirst) (items()[0] || btn).focus();
    }
    function close(returnFocus) {
      if (menu.hidden) return;
      menu.hidden = true; btn.setAttribute('aria-expanded', 'false');
      if (returnFocus) btn.focus();
    }
    btn.addEventListener('click', e => { if (menu.hidden) open(e.detail === 0); else close(false); });
    btn.addEventListener('keydown', e => {
      if (e.key === 'ArrowDown') { e.preventDefault(); open(true); }
    });
    menu.addEventListener('keydown', e => {
      const list = items(), i = list.indexOf(document.activeElement);
      if (e.key === 'Escape') { e.preventDefault(); close(true); }
      else if (e.key === 'ArrowDown') { e.preventDefault(); list[(i + 1) % list.length].focus(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); list[(i - 1 + list.length) % list.length].focus(); }
      else if (e.key === 'Tab') close(false);
    });
    document.addEventListener('click', e => { if (!root.contains(e.target)) close(false); });
    document.addEventListener('keydown', e => { if (e.key === 'Escape' && !menu.hidden) close(true); });
    out.addEventListener('click', () => { close(false); (current.onSignOut || signOut)(); });
    paint(opts || {});
    return { update: paint, close: () => close(false) };
  }

  // Sign-out from anywhere: end this session, then the public landing page.
  // replace(): the signed-in page is not left in history for Back to show again.
  function signOut() {
    try { if (global.ApexAPI) global.ApexAPI.auth.logout(); } catch (e) { /* the session is cleared locally anyway */ }
    location.replace('index.html');
  }

  global.ApexAccountMenu = { mount, signOut, initials };
})(window);
