'use strict';
/* Expanded patient search (search.html), opened from the homepage's "See more".
 *
 * Data (ApexRX API, js/api.js):
 *   GET /search/pharmacies           q + price range + location/radius + sort, filtered and
 *                                    sorted by the server, so every filter combines and works
 *                                    on any number of results. Sent with record=false: the
 *                                    homepage already counted this search in search insights.
 *   GET /search/pharmacies/{id}      the selected pharmacy, with everything it lists.
 * Branches without coordinates have no distance (the API returns null, never an estimate).
 *
 * Map and directions (free OpenStreetMap services, no key, no billing):
 *   tiles     tile.openstreetmap.org        (OSM tile usage policy: light use, attribution)
 *   routing   routing.openstreetmap.de      (FOSSGIS OSRM, car and foot; fair use)
 *   places    nominatim.openstreetmap.org   (only when the patient presses Find; max 1 request/s)
 * If routing fails the map draws a straight line and says so; the Google Maps and
 * OpenStreetMap buttons always give turn-by-turn directions.
 *
 * The patient's location is asked for only when they press "Use my location", is kept
 * in memory for this tab, and is never put in the URL.
 */
(function () {
  const API = window.ApexAPI, SITE = window.ApexSite;
  if (!API || !SITE) return;

  const PAGE = 30;
  const ROUTER = 'https://routing.openstreetmap.de/routed-';
  const PLACES = 'https://nominatim.openstreetmap.org/search';
  const $ = id => document.getElementById(id);
  const t = SITE.t;
  const tf = (key, vars) => Object.keys(vars || {}).reduce((s, k) => s.split('{' + k + '}').join(vars[k]), t(key));
  const esc = v => String(v == null ? '' : v).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const num = (v, digits) => Number(v).toLocaleString(SITE.locale(), { maximumFractionDigits: digits });
  const hasCoords = x => x && x.latitude != null && x.longitude != null;

  /* ------------------------------------------------------------- state */
  const S = {
    q: '', min: null, max: null, sort: 'price', sortTouched: false, radius: '',
    items: [], total: 0, run: 0, controller: null, recordNext: false,
    origin: null,            // { lat, lng, source: 'gps' | 'place' | 'map', label }
    selectedId: null, selectedItem: null, detail: null, detailRun: 0,
    mode: 'car', routeRun: 0, routeController: null,
    pushedDetail: false      // true when this page added the pharmacy's history entry
  };

  /* --------------------------------------------------------------- URL */
  // ?q=&min=&max=&sort=&radius=&pharmacy=&lang= : a results page can be reloaded or shared.
  function readUrl() {
    const p = new URLSearchParams(location.search);
    S.q = (p.get('q') || '').trim().slice(0, 100);
    const n = k => { const v = p.get(k); return v !== null && v !== '' && isFinite(v) && Number(v) >= 0 ? Number(v) : null; };
    S.min = n('min'); S.max = n('max');
    S.sort = ['price', 'price_desc', 'distance', 'freshness'].includes(p.get('sort')) ? p.get('sort') : 'price';
    S.sortTouched = p.has('sort');
    S.radius = ['1', '2', '5', '10', '20'].includes(p.get('radius')) ? p.get('radius') : '';
    const id = Number(p.get('pharmacy'));
    return Number.isInteger(id) && id > 0 ? id : null;
  }
  function urlFor(pharmacyId) {
    const p = new URLSearchParams();
    if (S.q) p.set('q', S.q);
    if (S.min != null) p.set('min', S.min);
    if (S.max != null) p.set('max', S.max);
    if (S.sortTouched) p.set('sort', S.sort);
    if (S.radius) p.set('radius', S.radius);
    if (pharmacyId) p.set('pharmacy', pharmacyId);
    p.set('lang', SITE.lang());
    return location.pathname + '?' + p.toString();
  }
  function syncBackLink() {
    $('ps-back').href = 'index.html?' + new URLSearchParams(S.q ? { q: S.q, lang: SITE.lang() } : { lang: SITE.lang() }) + '#hero-search';
  }

  /* ----------------------------------------------------------- filters */
  function readPrices() {
    const parse = el => {
      const raw = el.value.trim();
      if (raw === '') return { ok: true, value: null };
      const v = Number(raw);
      return Number.isFinite(v) && v >= 0 && !el.validity.badInput ? { ok: true, value: v } : { ok: false };
    };
    const a = parse($('ps-min')), b = parse($('ps-max'));
    if (!a.ok || !b.ok) return { error: t('ps_err_price') };
    if (a.value != null && b.value != null && a.value > b.value) return { error: t('ps_err_range') };
    return { min: a.value, max: b.value };
  }
  function effectiveSort() {
    return S.sort === 'distance' && !S.origin ? 'price' : S.sort;
  }
  function paintFilters() {
    $('ps-q').value = S.q;
    $('ps-min').value = S.min == null ? '' : S.min;
    $('ps-max').value = S.max == null ? '' : S.max;
    const distance = $('ps-sort').querySelector('option[value=distance]');
    distance.disabled = !S.origin;
    $('ps-sort').value = effectiveSort();
    $('ps-radius').disabled = !S.origin;
    $('ps-radius').value = S.origin ? S.radius : '';
    $('ps-radius-hint').hidden = !!S.origin;
    // The radius labels ("Any distance") are data-i18n; numbers stay as they are.
    paintOrigin();
  }

  /* ---------------------------------------------------------- results */
  async function load(append) {
    if (!S.q || S.q.length < 2) {
      S.items = []; S.total = 0;
      $('ps-results').innerHTML = `<li class="ps-empty">${esc(t('ps_no_query'))}</li>`;
      $('ps-count').textContent = ''; $('ps-more').hidden = true;
      return;
    }
    const prices = readPrices();
    $('ps-filter-error').textContent = prices.error || '';
    if (prices.error) return; // nothing is requested with an invalid range
    S.min = prices.min; S.max = prices.max;

    const run = ++S.run;
    if (S.controller) S.controller.abort();
    S.controller = typeof AbortController === 'function' ? new AbortController() : null;
    const params = { q: S.q, sort: effectiveSort(), limit: PAGE, offset: append ? S.items.length : 0 };
    if (!S.recordNext) params.record = false;
    S.recordNext = false;
    if (S.min != null) params.min_price = S.min;
    if (S.max != null) params.max_price = S.max;
    if (S.origin) {
      params.lat = S.origin.lat.toFixed(5); params.lng = S.origin.lng.toFixed(5);
      if (S.radius) params.radius_km = S.radius;
    }
    const list = $('ps-results');
    list.setAttribute('aria-busy', 'true');
    if (!append && !S.items.length) list.innerHTML = '<li class="ps-skel" aria-hidden="true"></li><li class="ps-skel" aria-hidden="true"></li><li class="ps-skel" aria-hidden="true"></li>';
    if (!append) $('ps-count').textContent = t('t_searching');
    $('ps-more').disabled = true;
    try {
      const page = await API.search.pharmacies(params, { signal: S.controller ? S.controller.signal : undefined });
      if (run !== S.run) return;
      S.items = append ? S.items.concat(page.items) : page.items;
      S.total = page.total;
      renderList();
    } catch (err) {
      if (run !== S.run || (err && err.name === 'AbortError')) return;
      S.items = []; S.total = 0;
      $('ps-count').textContent = '';
      // 4xx (an invalid filter) says what is wrong; anything else is a generic retry message.
      const text = err && err.status >= 400 && err.status < 500 && err.message ? err.message : (err && err.status === 0 ? err.message : t('t_search_error'));
      list.innerHTML = `<li class="ps-empty" role="alert">${esc(text)}</li>`;
      $('ps-more').hidden = true;
    } finally {
      if (run === S.run) { list.setAttribute('aria-busy', 'false'); $('ps-more').disabled = false; }
    }
  }

  function renderList() {
    const list = $('ps-results');
    if (S.items[0]) $('ps-cur').textContent = '(' + S.items[0].currency + ')';
    if (!S.items.length) {
      $('ps-count').textContent = '';
      list.innerHTML = `<li class="ps-empty">${esc(t('ps_empty'))}</li>`;
      $('ps-more').hidden = true;
      return;
    }
    $('ps-count').textContent = S.items.length < S.total
      ? tf('ps_count_of', { a: S.items.length, n: S.total })
      : S.total === 1 ? t('ps_count_one') : tf('ps_count', { n: S.total });
    const lowest = Math.min(...S.items.map(x => Number(x.unit_price)));
    list.innerHTML = S.items.map((x, i) => {
      const status = SITE.stockClass(x.availability_status);
      const place = x.location_name && x.location_name !== x.pharmacy_name ? `${x.pharmacy_name} (${x.location_name})` : x.pharmacy_name;
      const dist = x.distance_km != null ? `<span class="ps-dist">${esc(tf('ps_km', { n: num(x.distance_km, x.distance_km < 10 ? 1 : 0) }))}</span>`
        : S.origin ? `<span>${esc(t('ps_no_coords'))}</span>` : '';
      const best = S.items.length > 1 && Number(x.unit_price) === lowest ? `<span class="ps-best">${esc(t('ps_cheapest'))}</span>` : '';
      return `<li class="ps-card" data-location="${x.location_id}" data-offer="${x.offer_id}">
  <div class="ps-card-top"><h3>${esc(SITE.medicineLabel(x))}</h3><span class="ps-price">${esc(SITE.formatPrice(x.unit_price, x.currency))}</span></div>
  <p class="ps-place">${esc(place)}</p>
  ${x.address ? `<p class="ps-addr">${esc(x.address)}</p>` : ''}
  <div class="ps-meta"><span class="rstock ${status[0]}">${esc(t(status[1]))}</span>${dist}${best}<span>${esc(t('t_updated') + ' ' + SITE.formatAge(x.last_updated))}</span></div>
  <button type="button" class="ps-btn" data-open="${i}">${esc(t('ps_view'))}</button>
</li>`;
    }).join('');
    $('ps-more').hidden = S.items.length >= S.total;
  }

  /* ---------------------------------------------------------- location */
  function setOrigin(origin) {
    S.origin = origin;
    // Setting a location means "what is near me": nearest first. The patient can
    // still pick another order afterwards; the distances stay on every card.
    S.sort = 'distance'; S.sortTouched = true;
    paintFilters();
    history.replaceState(history.state, '', urlFor(S.selectedId));
    load(false);
    if (S.detail) drawMap();
  }
  function clearOrigin() {
    S.origin = null; S.radius = '';
    if (S.sort === 'distance') { S.sort = 'price'; S.sortTouched = false; }
    paintFilters();
    history.replaceState(history.state, '', urlFor(S.selectedId));
    load(false);
    if (S.detail) drawMap();
  }
  function originLabel() {
    if (!S.origin) return '';
    return S.origin.source === 'gps' ? t('ps_loc_current') : S.origin.source === 'map' ? t('ps_loc_map') : S.origin.label;
  }
  function paintOrigin() {
    $('ps-origin').hidden = !S.origin;
    $('ps-origin-text').textContent = originLabel();
  }
  function geolocate(msg) {
    if (!navigator.geolocation || typeof navigator.geolocation.getCurrentPosition !== 'function') { msg.textContent = t('ps_loc_unavailable'); return; }
    msg.textContent = t('ps_locating');
    navigator.geolocation.getCurrentPosition(
      pos => { msg.textContent = ''; setOrigin({ lat: pos.coords.latitude, lng: pos.coords.longitude, source: 'gps' }); },
      err => { msg.textContent = t(err && err.code === 1 ? 'ps_loc_denied' : 'ps_loc_unavailable'); },
      { enableHighAccuracy: true, timeout: 15000, maximumAge: 60000 }
    );
  }
  let lastPlaceSearch = 0;
  async function findPlace(input, listEl, msg) {
    const q = input.value.trim();
    if (q.length < 2) { input.focus(); return; }
    // Nominatim's usage policy: at most one request per second, only on demand.
    const wait = 1100 - (Date.now() - lastPlaceSearch);
    if (wait > 0) await new Promise(r => setTimeout(r, wait));
    lastPlaceSearch = Date.now();
    msg.textContent = t('ps_loading'); listEl.hidden = true;
    try {
      const url = PLACES + '?' + new URLSearchParams({ format: 'jsonv2', countrycodes: 'rw', limit: '5', 'accept-language': SITE.lang(), q });
      const res = await fetch(url, { headers: { Accept: 'application/json' } });
      if (!res.ok) throw new Error(String(res.status));
      const places = (await res.json()).filter(p => isFinite(p.lat) && isFinite(p.lon));
      msg.textContent = places.length ? '' : t('ps_place_none');
      if (!places.length) return;
      listEl.innerHTML = `<li class="ps-places-head">${esc(t('ps_place_pick'))}</li>` + places.map((p, i) =>
        `<li><button type="button" data-place="${i}">${esc(p.display_name)}</button></li>`).join('');
      listEl.hidden = false;
      listEl.onclick = e => {
        const b = e.target.closest('[data-place]'); if (!b) return;
        const p = places[+b.dataset.place];
        listEl.hidden = true; input.value = '';
        setOrigin({ lat: Number(p.lat), lng: Number(p.lon), source: 'place', label: String(p.display_name).split(',').slice(0, 2).join(',') });
      };
      listEl.querySelector('button').focus();
    } catch (e) {
      msg.textContent = t('ps_place_error');
    }
  }

  /* ---------------------------------------------------- selected pharmacy */
  function showList() {
    S.selectedId = null; S.detail = null;
    $('ps-detail-view').hidden = true; $('ps-list-view').hidden = false;
    const card = S.lastOpened && document.querySelector(`.ps-card[data-location="${S.lastOpened}"] button`);
    if (card) card.focus();
  }
  async function openDetail(locationId, item, push) {
    S.selectedId = locationId; S.selectedItem = item || null; S.lastOpened = locationId;
    if (push) { history.pushState({ pharmacy: locationId }, '', urlFor(locationId)); S.pushedDetail = true; }
    $('ps-list-view').hidden = true; $('ps-detail-view').hidden = false;
    $('ps-info').innerHTML = `<p class="ps-msg">${esc(t('ps_loading'))}</p>`;
    $('ps-directions').innerHTML = ''; $('ps-route-msg').textContent = '';
    $('ps-detail-view').scrollIntoView({ block: 'start' });
    const run = ++S.detailRun;
    try {
      const detail = await API.search.pharmacy(locationId);
      if (run !== S.detailRun) return;
      S.detail = detail;
      renderInfo(); drawMap();
    } catch (err) {
      if (run !== S.detailRun) return;
      S.detail = null;
      $('ps-info').innerHTML = `<p class="ps-error" role="alert">${esc(err && err.status === 404 ? t('ps_not_found') : t('t_search_error'))}</p>`;
      showMapMessage('');
    }
  }
  function isSearched(m) {
    if (S.selectedItem) return m.offer_id === S.selectedItem.offer_id;
    const q = S.q.toLowerCase();
    return !!q && [m.product_name, m.drug_name].some(v => String(v || '').toLowerCase().includes(q));
  }
  function renderInfo() {
    const d = S.detail;
    const where = [d.address, d.city, d.region].filter(Boolean).join(', ');
    const phone = d.phone ? `<a href="tel:${esc(String(d.phone).replace(/[^\d+]/g, ''))}">${esc(d.phone)}</a>` : '';
    const searched = d.medicines.find(isSearched);
    const status = searched ? SITE.stockClass(searched.availability_status) : null;
    $('ps-info').innerHTML = `<h2 tabindex="-1" id="ps-detail-title">${esc(d.pharmacy_name)}</h2>
${d.location_name && d.location_name !== d.pharmacy_name ? `<p class="ps-branch">${esc(d.location_name)}</p>` : ''}
<dl class="ps-facts">
  ${where ? `<dt>${esc(t('ps_address'))}</dt><dd>${esc(where)}</dd>` : ''}
  ${phone ? `<dt>${esc(t('ps_phone'))}</dt><dd>${phone}</dd>` : ''}
</dl>
${searched ? `<div class="ps-searched"><small>${esc(t('ps_searched'))}</small>
  <strong>${esc(SITE.medicineLabel(searched))}</strong>
  <span class="ps-price">${esc(SITE.formatPrice(searched.unit_price, searched.currency))}</span>
  <span class="ps-meta"><span class="rstock ${status[0]}">${esc(t(status[1]))}</span><span>${esc(t('t_updated') + ' ' + SITE.formatAge(searched.last_updated))}</span></span></div>` : ''}
${d.medicines.length ? `<h3>${esc(t('ps_other_meds'))}</h3><ul class="ps-medlist">${d.medicines.map(m => {
      const st = SITE.stockClass(m.availability_status);
      return `<li class="${isSearched(m) ? 'match' : ''}"><span>${esc(SITE.medicineLabel(m))}</span><span><span class="rstock ${st[0]}">${esc(t(st[1]))}</span> <span class="ps-medprice">${esc(SITE.formatPrice(m.unit_price, m.currency))}</span></span></li>`;
    }).join('')}</ul>` : ''}`;
    const title = $('ps-detail-title'); if (title) title.focus({ preventScroll: true });
  }

  /* --------------------------------------------------------------- map */
  let map = null, layers = null;
  function ensureMap() {
    if (map || !window.L) return map;
    map = L.map('ps-map', { scrollWheelZoom: false, tap: true });
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    }).addTo(map);
    map.attributionControl.addAttribution('Routes: <a href="https://routing.openstreetmap.de/about.html">FOSSGIS OSRM</a>');
    layers = L.layerGroup().addTo(map);
    // Tapping the map sets the starting point (for patients who won't share their location).
    map.on('click', e => setOrigin({ lat: e.latlng.lat, lng: e.latlng.lng, source: 'map' }));
    return map;
  }
  const pin = cls => L.divIcon({ className: '', html: `<div class="ps-pin ${cls}"></div>`, iconSize: [22, 22], iconAnchor: [11, 22], popupAnchor: [0, -20] });
  function showMapMessage(text) {
    const el = $('ps-map');
    let box = $('ps-map-empty');
    if (!box) { box = document.createElement('div'); box.id = 'ps-map-empty'; box.className = 'ps-map ps-map-empty'; el.after(box); }
    box.hidden = !text; box.textContent = text;
    el.hidden = !!text;
  }
  function drawMap() {
    const d = S.detail; if (!d) return;
    paintDirections();
    if (!hasCoords(d)) {
      showMapMessage(t(d.address || d.city ? 'ps_no_map' : 'ps_no_address'));
      $('ps-route-msg').textContent = '';
      return;
    }
    showMapMessage('');
    if (!ensureMap()) return;
    map.invalidateSize();
    layers.clearLayers();
    const dest = [Number(d.latitude), Number(d.longitude)];
    L.marker(dest, { icon: pin('pharmacy'), title: d.pharmacy_name, keyboard: true }).addTo(layers).bindPopup(esc(d.pharmacy_name));
    if (!S.origin) {
      map.setView(dest, 16);
      $('ps-route-msg').textContent = t('ps_start_hint');
      return;
    }
    const from = [S.origin.lat, S.origin.lng];
    L.marker(from, { icon: pin('origin'), title: t('ps_you'), keyboard: true }).addTo(layers).bindPopup(esc(t('ps_you')));
    map.fitBounds(L.latLngBounds([from, dest]), { padding: [40, 40], maxZoom: 16 });
    drawRoute(from, dest);
  }
  async function drawRoute(from, dest) {
    const run = ++S.routeRun;
    if (S.routeController) S.routeController.abort();
    S.routeController = typeof AbortController === 'function' ? new AbortController() : null;
    const timer = S.routeController && setTimeout(() => S.routeController.abort(), 12000);
    $('ps-route-msg').textContent = t('ps_route_loading');
    try {
      const url = `${ROUTER}${S.mode}/route/v1/driving/${from[1]},${from[0]};${dest[1]},${dest[0]}?overview=full&geometries=geojson`;
      const res = await fetch(url, { signal: S.routeController ? S.routeController.signal : undefined });
      const body = res.ok ? await res.json() : null;
      if (run !== S.routeRun) return;
      const route = body && body.code === 'Ok' && body.routes && body.routes[0];
      if (!route) throw new Error('no route');
      const line = L.geoJSON(route.geometry, { style: { color: '#1a9458', weight: 6, opacity: .85 } }).addTo(layers);
      map.fitBounds(line.getBounds(), { padding: [40, 40], maxZoom: 17 });
      $('ps-route-msg').innerHTML = `<span class="ps-route-sum">${esc(tf('ps_route_summary', { d: num(route.distance / 1000, 1), m: Math.max(1, Math.round(route.duration / 60)) }))}</span>`;
    } catch (e) {
      if (run !== S.routeRun) return;
      // Never pretend: a dashed straight line, labelled as such.
      L.polyline([from, dest], { color: '#0f1a3d', weight: 3, dashArray: '6 8', opacity: .7 }).addTo(layers);
      $('ps-route-msg').textContent = t('ps_route_fail');
    } finally { if (timer) clearTimeout(timer); }
  }
  function paintDirections() {
    const d = S.detail, box = $('ps-directions');
    const coords = hasCoords(d) ? `${Number(d.latitude)},${Number(d.longitude)}` : null;
    // Without coordinates: the address, plus the district and country when the address lacks them.
    const parts = [d.address];
    [d.city, 'Rwanda'].forEach(p => { if (p && !String(d.address || '').toLowerCase().includes(String(p).toLowerCase())) parts.push(p); });
    const destination = coords || parts.filter(Boolean).join(', ');
    if (!coords && !d.address && !d.city) { box.innerHTML = ''; return; }
    const g = new URLSearchParams({ api: '1', destination, travelmode: S.mode === 'foot' ? 'walking' : 'driving' });
    if (S.origin) g.set('origin', `${S.origin.lat.toFixed(5)},${S.origin.lng.toFixed(5)}`);
    let osm = '';
    if (coords) {
      osm = S.origin
        ? `https://www.openstreetmap.org/directions?engine=fossgis_osrm_${S.mode}&route=${S.origin.lat.toFixed(5)},${S.origin.lng.toFixed(5)};${coords}`
        : `https://www.openstreetmap.org/?mlat=${Number(d.latitude)}&mlon=${Number(d.longitude)}#map=17/${Number(d.latitude)}/${Number(d.longitude)}`;
    }
    box.innerHTML = `<a class="primary" id="ps-dir-google" target="_blank" rel="noopener" href="https://www.google.com/maps/dir/?${esc(g.toString())}">${esc(t('ps_open_google'))}</a>`
      + (osm ? `<a id="ps-dir-osm" target="_blank" rel="noopener" href="${esc(osm)}">${esc(t('ps_open_osm'))}</a>` : '')
      + (d.phone ? `<a href="tel:${esc(String(d.phone).replace(/[^\d+]/g, ''))}">${esc(t('ps_call'))} ${esc(d.phone)}</a>` : '');
  }
  function setMode(mode) {
    S.mode = mode;
    $('ps-mode-car').setAttribute('aria-pressed', String(mode === 'car'));
    $('ps-mode-foot').setAttribute('aria-pressed', String(mode === 'foot'));
    if (S.detail) drawMap();
  }

  /* ------------------------------------------------------------ events */
  let priceTimer;
  ['ps-min', 'ps-max'].forEach(id => $(id).addEventListener('input', () => {
    clearTimeout(priceTimer);
    priceTimer = setTimeout(() => { load(false); history.replaceState(history.state, '', urlFor(S.selectedId)); }, 450);
  }));
  $('ps-sort').addEventListener('change', e => {
    S.sort = e.target.value; S.sortTouched = true;
    history.replaceState(history.state, '', urlFor(S.selectedId)); load(false);
  });
  $('ps-radius').addEventListener('change', e => {
    S.radius = e.target.value;
    history.replaceState(history.state, '', urlFor(S.selectedId)); load(false);
  });
  $('ps-filters').addEventListener('submit', e => e.preventDefault());
  $('ps-filters').addEventListener('reset', e => {
    e.preventDefault();
    S.min = S.max = null; S.sort = 'price'; S.sortTouched = false; S.radius = ''; S.origin = null;
    $('ps-min').value = ''; $('ps-max').value = ''; $('ps-filter-error').textContent = ''; $('ps-loc-msg').textContent = '';
    $('ps-places').hidden = true;
    paintFilters();
    history.replaceState(history.state, '', urlFor(null)); load(false);
  });
  $('ps-search').addEventListener('submit', e => {
    e.preventDefault();
    const q = $('ps-q').value.trim().slice(0, 100);
    if (q.length < 2) { $('ps-q').focus(); return; }
    S.q = q; S.recordNext = true; // a new search, so it counts in search insights
    S.items = [];
    syncBackLink();
    if (S.selectedId) { history.pushState(null, '', urlFor(null)); showList(); } else history.replaceState(null, '', urlFor(null));
    load(false);
  });
  $('ps-more').addEventListener('click', () => load(true));
  $('ps-results').addEventListener('click', e => {
    const b = e.target.closest('[data-open]'); if (!b) return;
    const item = S.items[+b.dataset.open];
    if (item) openDetail(item.location_id, item, true);
  });
  // Back to the list: through history when this page opened the pharmacy (so the
  // browser's Back button behaves the same), otherwise in place (a shared link).
  $('ps-back-results').addEventListener('click', () => {
    if (S.pushedDetail) history.back();
    else { history.replaceState(null, '', urlFor(null)); showList(); }
  });
  window.addEventListener('popstate', () => {
    const id = readUrlPharmacy();
    S.pushedDetail = false;
    if (id) openDetail(id, S.items.find(x => x.location_id === id) || null, false); else showList();
  });
  function readUrlPharmacy() { const id = Number(new URLSearchParams(location.search).get('pharmacy')); return Number.isInteger(id) && id > 0 ? id : null; }

  // Location controls: the same actions in the filters and next to the map.
  [['ps-geo', 'ps-loc-msg'], ['ps-geo-2', 'ps-route-msg']].forEach(([btn, msg]) => $(btn).addEventListener('click', () => geolocate($(msg))));
  [['ps-place', 'ps-place-go', 'ps-places', 'ps-loc-msg'], ['ps-place-2', 'ps-place-go-2', 'ps-places-2', 'ps-route-msg']].forEach(([input, btn, listId, msg]) => {
    const go = () => findPlace($(input), $(listId), $(msg));
    $(btn).addEventListener('click', go);
    $(input).addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); go(); } });
  });
  $('ps-origin-clear').addEventListener('click', clearOrigin);
  $('ps-mode-car').addEventListener('click', () => setMode('car'));
  $('ps-mode-foot').addEventListener('click', () => setMode('foot'));

  // Language: script.js translates data-i18n text; dynamic parts are redrawn here.
  window.addEventListener('apexrx:lang', () => {
    syncBackLink(); paintOrigin();
    if (S.items.length) renderList();
    if (S.detail) { renderInfo(); drawMap(); }
    history.replaceState(history.state, '', urlFor(S.selectedId));
  });

  /* ------------------------------------------------------------- start */
  const pharmacy = readUrl();
  paintFilters(); syncBackLink();
  load(false);
  if (pharmacy) { history.replaceState({ pharmacy }, '', urlFor(pharmacy)); openDetail(pharmacy, null, false); }
})();
