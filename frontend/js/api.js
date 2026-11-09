/* ApexRX Smart API client.
 *
 * One small, dependency-free wrapper around the FastAPI backend (see the
 * backend README "API Overview" and http://127.0.0.1:8000/docs).
 *
 * Base URL: js/config.js sets window.APEX_CONFIG.API_BASE_URL and must load
 * before this script. Without it, the local development server is used.
 *
 * The access token is kept in sessionStorage, so it is cleared when the tab
 * closes. It is never written to localStorage.
 *
 * Sessions (see the root README, "Sessions"): every token names a server-side
 * session that the backend ends on sign-out, after SESSION_IDLE_TIMEOUT_MINUTES
 * (default 30) without user activity, or at its maximum age. This file:
 *   - reports real user activity (pointer, keyboard, wheel, touch, page
 *     navigation) to POST /auth/session/activity at most once a minute, which
 *     also renews the short-lived access token. Requests made by code
 *     (refreshes, searches as you type, warm-up) are NOT activity;
 *   - warns two minutes before the inactivity limit ("Stay signed in"), then
 *     signs out (server and browser) with the reason "idle";
 *   - keeps tabs of the same session in step (BroadcastChannel): activity in one
 *     tab counts for all of them, a renewed token is shared, and signing out
 *     (or expiry) in one signs them all out. A tab only ever adopts a token for
 *     the session it already has, so nothing is signed in again after a sign-out;
 *   - reloads a page restored from the back/forward cache after the session
 *     ended, so private data is not shown again.
 * Every sign-out fires window event "apexrx:signed-out" with detail.reason:
 * "signed_out" (this tab), "other_tab", "idle", "expired" or "revoked".
 *
 * "Known browser" device tokens (one per account, from successful sign-ins)
 * are kept in localStorage and sent with later sign-ins for that account, so
 * someone else's wrong passwords cannot lock the owner out on this browser.
 * They are not credentials: the password is always required.
 */
(function (global) {
  'use strict';

  var DEFAULT_BASE =
    window.APEX_CONFIG?.API_BASE_URL || 'http://127.0.0.1:8000';
  var SESSION_KEY = 'apexrx_session';
  // Generous, because a free hosting instance that has gone to sleep can take
  // 30 seconds or more to answer its first request (see warmUp below).
  var TIMEOUT_MS = 45000;

  function resolveBase() {
    var meta = document.querySelector('meta[name="apexrx-api-base"]');
    var base = global.APEXRX_API_BASE || (meta && meta.content) || DEFAULT_BASE;
    return String(base).replace(/\/+$/, '');
  }
  var BASE = resolveBase();

  /* ---------------------------------------------------------------- errors */
  function ApiError(status, message, data) {
    this.name = 'ApiError';
    this.status = status;
    this.message = message;
    this.data = data || null;
  }
  ApiError.prototype = Object.create(Error.prototype);
  ApiError.prototype.constructor = ApiError;

  // FastAPI returns {"detail": "..."} for app errors and
  // {"detail": [{loc, msg}, ...]} for validation errors.
  function messageFrom(status, data) {
    var detail = data && data.detail;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail) && detail.length) {
      return detail.map(function (d) {
        var field = Array.isArray(d.loc) ? d.loc.filter(function (p) { return p !== 'body' && p !== 'query'; }).join('.') : '';
        var msg = String(d.msg || 'Invalid value').replace(/^Value error, /, '');
        return field ? field + ': ' + msg : msg;
      }).join(' ');
    }
    if (status === 0) return 'Cannot reach the ApexRX server. Check your connection and try again.';
    if (status >= 500) return 'The ApexRX server is having trouble. Please try again shortly.';
    return 'Request failed (' + status + ').';
  }

  /* --------------------------------------------------------------- session */
  function readSession() {
    try {
      var s = JSON.parse(sessionStorage.getItem(SESSION_KEY) || 'null');
      if (s && s.token && s.expiresAt > Date.now()) return s;
    } catch (e) { /* storage unavailable or corrupt */ }
    clearSession();
    return null;
  }
  // The session id is in the (signed) token; reading it needs no secret.
  function sessionIdOf(token) {
    try {
      var part = String(token).split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
      return JSON.parse(atob(part + '==='.slice((part.length + 3) % 4))).sid || null;
    } catch (e) { return null; }
  }
  // t: a TokenResponse. extra: fields kept from the current session (email, idle limit).
  function saveSession(t, extra) {
    var prev = memorySession || {};
    var s = Object.assign({}, prev, extra || {}, {
      token: t.access_token,
      expiresAt: Date.now() + Math.max(0, (t.expires_in || 0) - 30) * 1000,
      sid: sessionIdOf(t.access_token)
    });
    if (t.idle_timeout_seconds) s.idleMs = t.idle_timeout_seconds * 1000;
    try { sessionStorage.setItem(SESSION_KEY, JSON.stringify(s)); } catch (e) { /* ignore */ }
    memorySession = s;
    return s;
  }
  function clearSession() {
    memorySession = null;
    try { sessionStorage.removeItem(SESSION_KEY); } catch (e) { /* ignore */ }
  }
  var memorySession = null;

  /* ------------------------------------------------- known-browser tokens */
  var DEVICE_KEY = 'apexrx_known_devices';
  var MAX_DEVICE_ENTRIES = 5;
  function deviceKeyFor(email) { return String(email || '').trim().toLowerCase(); }
  // Only well-formed entries survive: {token: string, savedAt: finite number}.
  // Anything else in storage (null, strings, arrays, junk) is dropped, so a
  // corrupted value can never break sign-in.
  function readDevices() {
    var clean = {};
    try {
      var d = JSON.parse(localStorage.getItem(DEVICE_KEY) || '{}');
      if (!d || typeof d !== 'object' || Array.isArray(d)) return clean;
      Object.keys(d).forEach(function (k) {
        var e = d[k];
        if (e && typeof e === 'object' && typeof e.token === 'string' && e.token &&
            typeof e.savedAt === 'number' && isFinite(e.savedAt)) {
          clean[k] = { token: e.token, savedAt: e.savedAt };
        }
      });
    } catch (e) { /* storage unavailable or corrupt */ }
    return clean;
  }
  function deviceTokenFor(email) {
    var entry = readDevices()[deviceKeyFor(email)];
    return entry ? entry.token : null;
  }
  // Best effort: never throws, so a successful sign-in is never reported as
  // failed because the known-browser list could not be updated.
  function saveDeviceToken(email, token) {
    try {
      if (typeof token !== 'string' || !token) return;
      var devices = readDevices();
      devices[deviceKeyFor(email)] = { token: token, savedAt: Date.now() };
      Object.keys(devices)
        .sort(function (a, b) { return devices[b].savedAt - devices[a].savedAt; })
        .slice(MAX_DEVICE_ENTRIES)
        .forEach(function (k) { delete devices[k]; });
      localStorage.setItem(DEVICE_KEY, JSON.stringify(devices));
    } catch (e) { /* storage unavailable: the browser is simply not remembered */ }
  }

  function currentToken() {
    var s = readSession() || (memorySession && memorySession.expiresAt > Date.now() ? memorySession : null);
    return s ? s.token : null;
  }

  /* -------------------------------------------------------------- activity */
  // While any request is in flight, <html> gets the class "apex-busy" (after a
  // short delay, so fast requests don't flicker), which shows a thin progress
  // bar at the top of the page. If the wait goes past a few seconds,
  // "apex-slow" is added too, with a note that the server may be starting up.
  var BUSY_DELAY_MS = 150;
  var SLOW_DELAY_MS = 4000;
  var inFlight = 0, busyTimer = null, slowTimer = null;
  function setRootClass(name, on) {
    var root = document.documentElement;
    if (root) root.classList.toggle(name, on);
  }
  function activityStart() {
    inFlight += 1;
    if (inFlight > 1) return;
    busyTimer = setTimeout(function () { setRootClass('apex-busy', true); }, BUSY_DELAY_MS);
    slowTimer = setTimeout(function () { setRootClass('apex-slow', true); }, SLOW_DELAY_MS);
  }
  function activityEnd() {
    inFlight = Math.max(0, inFlight - 1);
    if (inFlight) return;
    clearTimeout(busyTimer); clearTimeout(slowTimer);
    setRootClass('apex-busy', false); setRootClass('apex-slow', false);
  }
  function tracked(promise) {
    activityStart();
    return promise.then(function (v) { activityEnd(); return v; }, function (e) { activityEnd(); throw e; });
  }
  (function injectActivityStyles() {
    if (!document.head || document.getElementById('apex-activity-style')) return;
    var style = document.createElement('style');
    style.id = 'apex-activity-style';
    style.textContent =
      'html.apex-busy::before{content:"";position:fixed;top:0;left:0;right:0;height:3px;z-index:2147483647;' +
      'background:linear-gradient(90deg,transparent,var(--green,#008f64),transparent);background-size:40% 100%;' +
      'background-repeat:no-repeat;animation:apex-busy-bar 1.1s ease-in-out infinite;pointer-events:none}' +
      'html.apex-busy,html.apex-busy button,html.apex-busy a{cursor:progress}' +
      'html.apex-slow::after{content:"Still working\u2026 the server may be starting up, this can take up to a minute.";' +
      'position:fixed;left:50%;bottom:20px;transform:translateX(-50%);z-index:2147483647;max-width:calc(100% - 32px);' +
      'padding:10px 16px;border-radius:999px;background:#101f36;color:#fff;font:500 13px/1.4 Inter,Arial,sans-serif;' +
      'box-shadow:0 6px 24px rgba(0,0,0,.18);pointer-events:none;text-align:center}' +
      '@keyframes apex-busy-bar{0%{background-position:-40% 0}100%{background-position:140% 0}}' +
      '@media (prefers-reduced-motion:reduce){html.apex-busy::before{animation:none;background:var(--green,#008f64);opacity:.6}}';
    document.head.appendChild(style);
  })();

  /* --------------------------------------------------------------- request */
  function buildUrl(path, query) {
    var url = BASE + path;
    if (query) {
      var params = new URLSearchParams();
      Object.keys(query).forEach(function (k) {
        var v = query[k];
        if (v !== undefined && v !== null && v !== '') params.append(k, String(v));
      });
      var qs = params.toString();
      if (qs) url += '?' + qs;
    }
    return url;
  }

  /**
   * request(method, path, {query, body, form, auth=true, signal, quiet})
   * Resolves with parsed JSON (or null for 204). Rejects with ApiError.
   */
  function request(method, path, opts) {
    opts = opts || {};
    var headers = { Accept: 'application/json' };
    var body;
    if (opts.form) {
      body = opts.form; // FormData: the browser sets the multipart boundary
    } else if (opts.body !== undefined) {
      headers['Content-Type'] = 'application/json';
      body = JSON.stringify(opts.body);
    }
    if (opts.auth !== false) {
      var token = currentToken();
      if (token) headers.Authorization = 'Bearer ' + token;
    }

    var controller = typeof AbortController === 'function' ? new AbortController() : null;
    var timer = controller ? setTimeout(function () { controller.abort(); }, TIMEOUT_MS) : null;
    if (controller && opts.signal) {
      if (opts.signal.aborted) controller.abort();
      else opts.signal.addEventListener('abort', function () { controller.abort(); });
    }

    // quiet: background calls (activity reports) show no progress bar.
    return (opts.quiet ? function (p) { return p; } : tracked)(fetch(buildUrl(path, opts.query), {
      method: method,
      headers: headers,
      body: body,
      signal: controller ? controller.signal : undefined,
      credentials: 'omit'
    }).then(function (res) {
      if (timer) clearTimeout(timer);
      if (res.status === 204) return null;
      return res.text().then(function (text) {
        var data = null;
        if (text) { try { data = JSON.parse(text); } catch (e) { data = { detail: text }; } }
        if (!res.ok) {
          if (res.status === 401 && opts.auth !== false && headers.Authorization) {
            endSession(reasonOf(data), false);
          }
          throw new ApiError(res.status, messageFrom(res.status, data), data);
        }
        return data;
      });
    }, function (err) {
      if (timer) clearTimeout(timer);
      if (opts.signal && opts.signal.aborted) throw err; // caller cancelled
      throw new ApiError(0, messageFrom(0, null), { cause: String(err) });
    }));
  }

  // Authenticated file download. Resolves with a Blob (use URL.createObjectURL).
  function download(path) {
    var token = currentToken();
    return tracked(fetch(BASE + path, { headers: token ? { Authorization: 'Bearer ' + token } : {}, credentials: 'omit' })
      .then(function (res) {
        if (res.ok) return res.blob();
        return res.json().catch(function () { return null; }).then(function (data) {
          if (res.status === 401 && token) endSession(reasonOf(data), false);
          throw new ApiError(res.status, messageFrom(res.status, data), data);
        });
      }, function (err) { throw new ApiError(0, messageFrom(0, null), { cause: String(err) }); }));
  }

  // Wake the backend (and its database) as soon as a page opens, so a server
  // that went to sleep is already starting while the user reads or types.
  // Fire and forget: not tracked, no timeout, errors ignored.
  (function warmUp() {
    try { fetch(BASE + '/health', { credentials: 'omit', cache: 'no-store' }).catch(function () {}); } catch (e) { /* ignore */ }
  })();

  function emit(name, detail) {
    try { global.dispatchEvent(new CustomEvent(name, { detail: detail || {} })); } catch (e) { /* old browsers */ }
  }

  /* --------------------------------------------- session activity and expiry */
  var ACTIVITY_REPORT_MS = 60000;   // at most one activity report a minute
  var WARNING_MS = 120000;          // warn two minutes before the inactivity limit
  var DEFAULT_IDLE_MS = 30 * 60000;
  var channel = null;
  try { channel = new BroadcastChannel('apexrx-session'); } catch (e) { /* not supported */ }
  var lastActivity = Date.now();
  var lastReport = 0, reporting = false, warningEl = null;
  var signedInAtLoad = !!currentToken();

  function reasonOf(data) {
    var r = data && data.reason;
    if (r === 'session_idle') return 'idle';
    if (r === 'session_expired') return 'expired';
    return 'revoked';
  }
  function current() { return currentToken() ? memorySession || readSession() : null; }
  function idleMs() { var s = current(); return (s && s.idleMs) || DEFAULT_IDLE_MS; }
  function post2(type, extra) { if (channel) { try { channel.postMessage(Object.assign({ type: type }, extra)); } catch (e) { /* ignore */ } } }

  // End this tab's session: tell the server (unless it already ended it), the
  // other tabs of the same session, and the page.
  function endSession(reason, tellServer) {
    var s = memorySession || readSession();
    var token = s && s.token, sid = s && s.sid;
    var idleMinutes = Math.round(((s && s.idleMs) || DEFAULT_IDLE_MS) / 60000);
    clearSession();
    hideWarning();
    if (tellServer && token) {
      try {
        fetch(BASE + '/auth/logout', { method: 'POST', headers: { Authorization: 'Bearer ' + token },
          credentials: 'omit', keepalive: true }).catch(function () {});
      } catch (e) { /* ignore */ }
    }
    if (sid && reason !== 'other_tab') post2('signed-out', { sid: sid, reason: reason, idleMinutes: idleMinutes });
    emit('apexrx:signed-out', { reason: reason, idleMinutes: idleMinutes });
  }

  // Real user activity only. Called from input events, never from requests.
  function markActivity() {
    if (!currentToken()) return;
    lastActivity = Date.now();
    var s = current();
    post2('activity', { sid: s && s.sid, at: lastActivity });
    if (warningEl) hideWarning();
    reportActivity(false);
  }
  var reportTimer = null;
  // Reported at most every minute (a quarter of the limit if that is shorter).
  // Activity inside that interval is reported when it ends, so the server
  // never sees the user as idle earlier than this page does.
  function reportInterval() { return Math.min(ACTIVITY_REPORT_MS, idleMs() / 4); }
  function reportActivity(force) {
    var s = current();
    if (!s || reporting) return;
    if (!force && lastActivity <= lastReport) return;
    var wait = lastReport + reportInterval() - Date.now();
    if (!force && wait > 0) {
      if (!reportTimer) reportTimer = setTimeout(function () { reportTimer = null; reportActivity(false); }, wait);
      return;
    }
    reporting = true;
    lastReport = Date.now();
    request('POST', '/auth/session/activity', { quiet: true }).then(function (t) {
      var now = current();
      if (!now || now.sid !== s.sid) return; // signed out (or another account) meanwhile
      var saved = saveSession(t);
      post2('token', { sid: saved.sid, token: t });
    }, function () { /* a 401 already ended the session */ }).then(function () { reporting = false; });
  }

  function checkIdle() {
    if (!currentToken()) { hideWarning(); return; }
    var idle = Date.now() - lastActivity, limit = idleMs();
    if (idle >= limit) { endSession('idle', true); return; }
    var warnFrom = limit - Math.min(WARNING_MS, limit / 5);
    if (idle >= warnFrom) showWarning(Math.ceil((limit - idle) / 1000)); else hideWarning();
  }

  function showWarning(secondsLeft) {
    if (!document.body) return;
    if (!warningEl) {
      warningEl = document.createElement('div');
      warningEl.id = 'apex-idle-warning';
      warningEl.setAttribute('role', 'alertdialog');
      warningEl.setAttribute('aria-live', 'assertive');
      warningEl.setAttribute('aria-labelledby', 'apex-idle-text');
      warningEl.innerHTML = '<p id="apex-idle-text"><span>You will be signed out soon because of inactivity.</span> ' +
        '<strong id="apex-idle-left"></strong></p><button type="button" id="apex-idle-stay">Stay signed in</button>';
      warningEl.style.cssText = 'position:fixed;left:50%;bottom:24px;transform:translateX(-50%);z-index:2147483647;' +
        'max-width:calc(100% - 32px);width:440px;padding:16px 18px;border-radius:14px;background:#101f36;color:#fff;' +
        'font:500 14px/1.5 Inter,Arial,sans-serif;box-shadow:0 10px 35px rgba(0,0,0,.25);display:flex;gap:14px;' +
        'align-items:center;justify-content:space-between;flex-wrap:wrap';
      var btn = warningEl.querySelector('button');
      btn.style.cssText = 'border:0;border-radius:9px;padding:10px 14px;background:#008f64;color:#fff;font:700 13px Inter,Arial,sans-serif;cursor:pointer';
      btn.addEventListener('click', function () { lastActivity = Date.now(); hideWarning(); reportActivity(true); });
      document.body.appendChild(warningEl);
      btn.focus();
    }
    var m = Math.floor(secondsLeft / 60), sec = secondsLeft % 60;
    warningEl.querySelector('#apex-idle-left').textContent = m + ':' + (sec < 10 ? '0' : '') + sec;
  }
  function hideWarning() { if (warningEl) { warningEl.remove(); warningEl = null; } }

  if (channel) {
    channel.onmessage = function (ev) {
      var d = ev.data || {}, s = current();
      if (!s || !d.sid || d.sid !== s.sid) return; // only tabs of the same session
      if (d.type === 'activity') { lastActivity = Math.max(lastActivity, d.at || 0); hideWarning(); }
      else if (d.type === 'token' && d.token) saveSession(d.token);
      else if (d.type === 'signed-out') endSession(d.reason === 'idle' ? 'idle' : 'other_tab', false);
    };
  }
  ['pointerdown', 'keydown', 'wheel', 'touchstart'].forEach(function (name) {
    global.addEventListener(name, markActivity, { passive: true, capture: true });
  });
  setInterval(checkIdle, 5000);
  document.addEventListener('visibilitychange', function () { if (document.visibilityState === 'visible') checkIdle(); });
  // Opening or reloading a page is navigation, i.e. activity.
  if (signedInAtLoad) setTimeout(function () { markActivity(); checkIdle(); }, 0);
  // Back/forward cache: a page kept in memory from before a sign-out reloads.
  global.addEventListener('pageshow', function (e) {
    if (e.persisted && signedInAtLoad && !currentToken()) location.reload();
  });

  var get = function (p, q, o) { return request('GET', p, Object.assign({ query: q }, o)); };
  var post = function (p, b, o) { return request('POST', p, Object.assign({ body: b }, o)); };
  var put = function (p, b, o) { return request('PUT', p, Object.assign({ body: b }, o)); };
  var patch = function (p, b, o) { return request('PATCH', p, Object.assign({ body: b }, o)); };
  var del = function (p, o) { return request('DELETE', p, o); };
  var enc = encodeURIComponent;

  function org(id) { return '/organizations/' + enc(id); }
  function stockPath(orgId, locId, productId) {
    return org(orgId) + '/locations/' + enc(locId) + '/stock/' + enc(productId);
  }
  function po(id) { return '/purchase-orders/' + enc(id); }

  /* ------------------------------------------------------------- endpoints */
  var api = {
    baseUrl: BASE,
    ApiError: ApiError,
    request: request,

    health: function () { return get('/health', null, { auth: false }); },

    session: {
      isSignedIn: function () { return !!currentToken(); },
      // The signed-in email (kept from sign-in), or null.
      email: function () { var s = current(); return (s && s.email) || null; },
      clear: clearSession
    },

    invitations: {
      // Owners and managers of the organization.
      list: function (orgId) { return get(org(orgId) + '/invitations'); },
      create: function (orgId, email, role) { return post(org(orgId) + '/invitations', { email: email, role: role }); },
      resend: function (orgId, invId) { return post(org(orgId) + '/invitations/' + enc(invId) + '/resend'); },
      revoke: function (orgId, invId) { return post(org(orgId) + '/invitations/' + enc(invId) + '/revoke'); },
      // The invitee, from the emailed link.
      inspect: function (token) { return post('/invitations/inspect', { token: token }, { auth: false }); },
      acceptNew: function (token, name, password) {
        return post('/invitations/accept-new', { token: token, name: name, password: password }, { auth: false });
      },
      accept: function (token) { return post('/invitations/accept', { token: token }); }
    },

    auth: {
      // Email verification by emailed link. status/send need a session;
      // verify is opened from the link (verify-email.html) and needs none.
      email: {
        status: function () { return get('/auth/email/status'); },
        send: function (next) { return post('/auth/email/send', next ? { next: next } : {}); },
        verify: function (token) { return post('/auth/email/verify', { token: token }, { auth: false }); }
      },
      register: function (data) { return post('/auth/register', data, { auth: false }); },
      login: function (email, password) {
        var body = { email: email, password: password };
        var known = deviceTokenFor(email);
        if (known) body.device_token = known;
        return post('/auth/login', body, { auth: false })
          .then(function (t) {
            memorySession = null; // a new sign-in never inherits the previous session's fields
            saveSession(t, { email: String(email).trim().toLowerCase() });
            saveDeviceToken(email, t.device_token);
            lastActivity = Date.now(); lastReport = Date.now();
            return t;
          });
      },
      // Sign out this session (server and every tab of it). Synchronous for the
      // page: the session is cleared and "apexrx:signed-out" fires immediately.
      logout: function () { endSession('signed_out', true); },
      session: function () { return get('/auth/session'); },
      // What works on this server (public): email delivery is temporarily disabled.
      capabilities: function () { return get('/auth/capabilities', null, { auth: false }); },
      // Adopt a TokenResponse obtained another way (accepting an invitation).
      useToken: function (t, email) {
        memorySession = null;
        saveSession(t, { email: email ? String(email).trim().toLowerCase() : null });
        lastActivity = Date.now(); lastReport = Date.now();
      },
      password: {
        forgot: function (email) { return post('/auth/password/forgot', { email: email }, { auth: false }); },
        check: function (token) { return post('/auth/password/reset/check', { token: token }, { auth: false }); },
        reset: function (token, newPassword) {
          return post('/auth/password/reset', { token: token, new_password: newPassword }, { auth: false });
        }
      },
      me: function () { return get('/auth/me'); },
      updateMe: function (data) { return patch('/auth/me', data); },
      changePassword: function (current, next) {
        return post('/auth/me/password', { current_password: current, new_password: next });
      }
    },

    /* Patients (public, no account). Never returns exact quantities. */
    search: {
      medicines: function (q, page) { return get('/search/medicines', Object.assign({ q: q }, page), { auth: false }); },
      // params: {q | product_id | drug_id, lat, lng, radius_km, availability, max_price, sort, limit, offset}
      pharmacies: function (params, opts) { return get('/search/pharmacies', params, Object.assign({ auth: false }, opts)); },
      pharmacy: function (locationId, params) { return get('/search/pharmacies/' + enc(locationId), params, { auth: false }); }
    },

    catalogue: {
      drugs: function (params) { return get('/catalogue/drugs', params, { auth: false }); },
      products: function (params) { return get('/catalogue/products', params, { auth: false }); },
      drug: function (id) { return get('/catalogue/drugs/' + enc(id), null, { auth: false }); },
      product: function (id) { return get('/catalogue/products/' + enc(id), null, { auth: false }); },
      createDrug: function (data) { return post('/catalogue/drugs', data); },
      updateDrug: function (id, data) { return patch('/catalogue/drugs/' + enc(id), data); },
      createProduct: function (data) { return post('/catalogue/products', data); },
      updateProduct: function (id, data) { return patch('/catalogue/products/' + enc(id), data); }
    },

    organizations: {
      mine: function () { return get('/organizations'); },
      create: function (data) { return post('/organizations', data); },
      get: function (id) { return get(org(id)); },
      update: function (id, data) { return patch(org(id), data); },
      resubmit: function (id) { return post(org(id) + '/resubmit'); },

      members: function (id) { return get(org(id) + '/members'); },
      addMember: function (id, email, role) { return post(org(id) + '/members', { email: email, role: role }); },
      updateMember: function (id, membershipId, data) { return patch(org(id) + '/members/' + enc(membershipId), data); },
      removeMember: function (id, membershipId) { return del(org(id) + '/members/' + enc(membershipId)); },

      locations: function (id, params) { return get(org(id) + '/locations', params); },
      createLocation: function (id, data) { return post(org(id) + '/locations', data); },
      getLocation: function (id, locId) { return get(org(id) + '/locations/' + enc(locId)); },
      updateLocation: function (id, locId, data) { return patch(org(id) + '/locations/' + enc(locId), data); },

      documents: function (id) { return get(org(id) + '/documents'); },
      uploadDocument: function (id, documentType, file) {
        var form = new FormData();
        form.append('document_type', documentType);
        form.append('file', file, file.name);
        return request('POST', org(id) + '/documents', { form: form });
      },
      deleteDocument: function (id, docId) { return del(org(id) + '/documents/' + enc(docId)); },
      downloadDocument: function (id, docId) { return download(org(id) + '/documents/' + enc(docId) + '/download'); }
    },

    /* Stock (any member) and offers/prices (owners and managers). */
    inventory: {
      list: function (orgId, params) { return get(org(orgId) + '/inventory', params); },
      get: function (orgId, locId, productId) { return get(stockPath(orgId, locId, productId)); },
      setQuantity: function (orgId, locId, productId, quantity) {
        return put(stockPath(orgId, locId, productId), { quantity: quantity });
      },
      remove: function (orgId, locId, productId) { return del(stockPath(orgId, locId, productId)); },
      // offer: {unit_price, currency?, low_stock_threshold, is_listed}
      setOffer: function (orgId, locId, productId, offer) { return put(stockPath(orgId, locId, productId) + '/offer', offer); },
      removeOffer: function (orgId, locId, productId) { return del(stockPath(orgId, locId, productId) + '/offer'); },
      adjustments: function (orgId, locId, productId, page) { return get(stockPath(orgId, locId, productId) + '/adjustments', page); },
      confirmLocation: function (orgId, locId) { return post(org(orgId) + '/locations/' + enc(locId) + '/stock/confirm'); }
    },

    /* Pharmacies searching supplier stock (exact quantities). */
    supplierOffers: {
      // params: {pharmacy_organization_id (required), q, product_id, drug_id, supplier_organization_id,
      //          lat, lng, radius_km, min_quantity, max_price, sort, limit, offset}
      search: function (params, opts) { return get('/supplier-offers', params, opts); }
    },

    /* Each order carries `allowed_actions`; show only those buttons. */
    purchaseOrders: {
      list: function (params) { return get('/purchase-orders', params); },
      // data: {pharmacy_organization_id, supplier_organization_id, pharmacy_location_id,
      //        supplier_location_id?, notes?, items?: [{product_id, quantity}]}
      create: function (data) { return post('/purchase-orders', data); },
      get: function (id) { return get(po(id)); },
      update: function (id, data) { return patch(po(id), data); },
      remove: function (id) { return del(po(id)); },
      addItem: function (id, item) { return post(po(id) + '/items', item); }, // {product_id, quantity}
      updateItem: function (id, itemId, data) { return patch(po(id) + '/items/' + enc(itemId), data); },
      removeItem: function (id, itemId) { return del(po(id) + '/items/' + enc(itemId)); },
      reprice: function (id) { return post(po(id) + '/reprice'); },
      // action: submit | accept | counter | reject | accept-counter | start-processing |
      //         dispatch | mark-delivered | cancel
      // bodies: accept {supplier_location_id?, note?}; counter {items: [{purchase_order_item_id,
      //         confirmed_quantity, confirmed_unit_price}], note?}; reject/cancel {reason}; others {note?}
      // submit rejects with 409 and data.price_changes when supplier prices moved: call reprice().
      transition: function (id, action, body) { return post(po(id) + '/' + action, body || {}); }
    },

    admin: {
      organizations: function (params) { return get('/admin/organizations', params); },
      organizationCounts: function () { return get('/admin/organizations/counts'); },
      organization: function (id) { return get('/admin/organizations/' + enc(id)); },
      reviewOrganization: function (id, decision, notes) {
        return post('/admin/organizations/' + enc(id) + '/review', { decision: decision, notes: notes || null });
      },
      documents: function (params) { return get('/admin/documents', params); },
      downloadDocument: function (docId) { return download('/admin/documents/' + enc(docId) + '/download'); },
      reviewDocument: function (docId, decision, rejectionReason) {
        return post('/admin/documents/' + enc(docId) + '/review', { decision: decision, rejection_reason: rejectionReason || null });
      },
      users: function (params) { return get('/admin/users', params); },
      updateUser: function (id, data) { return patch('/admin/users/' + enc(id), data); },
      searchInsights: function (params) { return get('/admin/insights/searches', params); }
    }
  };

  global.ApexAPI = api;
})(window);
