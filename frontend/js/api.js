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
  var TIMEOUT_MS = 15000;

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
  function saveSession(token, expiresInSeconds) {
    var s = { token: token, expiresAt: Date.now() + Math.max(0, expiresInSeconds - 30) * 1000 };
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
   * request(method, path, {query, body, form, auth=true, signal})
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

    return fetch(buildUrl(path, opts.query), {
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
          if (res.status === 401 && opts.auth !== false) {
            clearSession();
            emit('apexrx:signed-out');
          }
          throw new ApiError(res.status, messageFrom(res.status, data), data);
        }
        return data;
      });
    }, function (err) {
      if (timer) clearTimeout(timer);
      if (opts.signal && opts.signal.aborted) throw err; // caller cancelled
      throw new ApiError(0, messageFrom(0, null), { cause: String(err) });
    });
  }

  // Authenticated file download. Resolves with a Blob (use URL.createObjectURL).
  function download(path) {
    var token = currentToken();
    return fetch(BASE + path, { headers: token ? { Authorization: 'Bearer ' + token } : {}, credentials: 'omit' })
      .then(function (res) {
        if (res.ok) return res.blob();
        return res.json().catch(function () { return null; }).then(function (data) {
          if (res.status === 401) {
            clearSession();
            emit('apexrx:signed-out');
          }
          throw new ApiError(res.status, messageFrom(res.status, data), data);
        });
      }, function (err) { throw new ApiError(0, messageFrom(0, null), { cause: String(err) }); });
  }

  function emit(name) {
    try { global.dispatchEvent(new CustomEvent(name)); } catch (e) { /* old browsers */ }
  }

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
      clear: clearSession
    },

    auth: {
      // Mobile number verification by SMS one-time code (signed in).
      phone: {
        status: function () { return get('/auth/phone/status'); },
        sendCode: function (phone) { return post('/auth/phone/send-code', { phone: phone }); },
        verify: function (phone, code) { return post('/auth/phone/verify', { phone: phone, code: code }); }
      },
      register: function (data) { return post('/auth/register', data, { auth: false }); },
      login: function (email, password) {
        var body = { email: email, password: password };
        var known = deviceTokenFor(email);
        if (known) body.device_token = known;
        return post('/auth/login', body, { auth: false })
          .then(function (t) {
            saveSession(t.access_token, t.expires_in);
            saveDeviceToken(email, t.device_token);
            return t;
          });
      },
      logout: function () { clearSession(); emit('apexrx:signed-out'); },
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
