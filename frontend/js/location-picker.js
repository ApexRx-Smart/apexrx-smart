'use strict';
/* Map location picker for a pharmacy branch or supplier depot.
 *
 *   const picker = ApexLocationPicker.mount(container, {
 *     value: { lat, lng } | null,  // the saved location, if any
 *     t: text => text,             // translation (dashboard); the registration
 *                                  // pages translate the DOM text instead
 *     buttonClass: 'secondary',    // the page's button style
 *     required: true,              // no "Remove the location" (every branch needs one)
 *     onChange(value, meta)        // value { lat, lng } or null; meta.address
 *   });                            // when a searched place was chosen
 *   picker.get(); picker.set(v); picker.refresh(); picker.disable(bool)
 *
 * Three ways to place the pin, none of which needs the user to be at the
 * branch: search for an address or place (OpenStreetMap Nominatim, Rwanda
 * only, at most one request per second, only when "Search" is pressed),
 * click or tap the map, or "Use my current location" (the browser asks for
 * permission only then). The pin can be dragged to adjust it. Nothing is
 * saved here: the page saves the value with the rest of its form, and the
 * server checks it again (in Rwanda, both coordinates or neither).
 *
 * Map tiles: OpenStreetMap (tile.openstreetmap.org, light use, attribution),
 * through the Leaflet copy in vendor/leaflet. If the map cannot load, search
 * and "Use my current location" still set the location.
 */
(function (global) {
  // A box around Rwanda (with a small margin); the server uses the same one.
  const RWANDA = { latMin: -2.9, latMax: -1.0, lngMin: 28.8, lngMax: 31.0 };
  const CENTER = [-1.95, 29.9];
  const PLACES = 'https://nominatim.openstreetmap.org/search';
  let lastSearch = 0;

  const inRwanda = v => v && v.lat >= RWANDA.latMin && v.lat <= RWANDA.latMax && v.lng >= RWANDA.lngMin && v.lng <= RWANDA.lngMax;
  const round = n => Math.round(Number(n) * 1e6) / 1e6;
  function el(tag, attrs, children) {
    const e = document.createElement(tag);
    Object.entries(attrs || {}).forEach(([k, v]) => {
      if (k === 'text') e.textContent = v; else if (v !== false && v != null) e.setAttribute(k, v === true ? '' : v);
    });
    (children || []).forEach(c => e.append(c));
    return e;
  }

  function mount(container, opts) {
    opts = opts || {};
    const t = opts.t || (s => s);
    const btn = opts.buttonClass || 'secondary';
    const lang = (document.documentElement.lang || 'en').slice(0, 2);
    let value = opts.value && isFinite(opts.value.lat) && isFinite(opts.value.lng)
      ? { lat: round(opts.value.lat), lng: round(opts.value.lng) } : null;
    let map = null, marker = null, disabled = false;

    const gps = el('button', { type: 'button', class: btn + ' lp-gps', text: t('Use my current location') });
    const query = el('input', { type: 'search', class: 'lp-query', maxlength: '200', autocomplete: 'off',
      placeholder: t('Search an address or place in Rwanda'), 'aria-label': t('Search an address or place in Rwanda') });
    const find = el('button', { type: 'button', class: btn + ' lp-find', text: t('Search') });
    const results = el('ul', { class: 'lp-results', hidden: true });
    const mapEl = el('div', { class: 'lp-map', role: 'region', 'aria-label': t('Map: click or tap to place the pin, then drag it to adjust') });
    const hint = el('p', { class: 'lp-hint', text: t('Click or tap the map to place the pin, then drag it to adjust.') });
    const status = el('p', { class: 'lp-status', role: 'status', 'aria-live': 'polite' });
    const message = el('p', { class: 'lp-message', role: 'alert' });
    const clear = el('button', { type: 'button', class: 'text-button lp-clear', text: t('Remove the location') });
    const root = el('div', { class: 'lp' }, [
      el('div', { class: 'lp-row' }, [gps]),
      el('div', { class: 'lp-row lp-search' }, [query, find]),
      results, mapEl, hint, status, message, clear
    ]);
    container.replaceChildren(root);

    function say(text) { message.textContent = text ? t(text) : ''; }
    function paintStatus() {
      if (value) {
        status.replaceChildren(el('span', { text: t('Selected location') }), document.createTextNode(': '),
          el('strong', { class: 'lp-coords', text: `${value.lat.toFixed(6)}, ${value.lng.toFixed(6)}` }));
      } else {
        status.replaceChildren(el('span', { text: t('No location chosen yet.') }));
      }
      clear.hidden = !value || disabled || !!opts.required;
    }
    function placeMarker(zoom) {
      if (!map) return;
      if (!value) { if (marker) { marker.remove(); marker = null; } return; }
      const ll = [value.lat, value.lng];
      if (!marker) {
        // A drawn pin (vendor/leaflet ships no marker images).
        const icon = L.divIcon({ className: '', html: '<div class="lp-pin"></div>', iconSize: [26, 26], iconAnchor: [13, 26] });
        marker = L.marker(ll, { icon, draggable: !disabled, keyboard: true, title: t('Location') }).addTo(map);
        marker.on('dragend', () => {
          const p = marker.getLatLng();
          choose({ lat: p.lat, lng: p.lng }, { source: 'drag' }, false);
        });
      } else marker.setLatLng(ll);
      if (zoom) map.setView(ll, Math.max(map.getZoom(), zoom));
    }
    // Accept a point only inside Rwanda; otherwise keep the previous one.
    function choose(v, meta, zoom) {
      if (!v) { value = null; say(''); paintStatus(); placeMarker(); if (opts.onChange) opts.onChange(null, meta || {}); return true; }
      const next = { lat: round(v.lat), lng: round(v.lng) };
      if (!inRwanda(next)) {
        say(meta && meta.source === 'gps'
          ? 'Your device is not in Rwanda right now. Search for the address or place the pin on the map instead.'
          : 'This point is outside Rwanda. Place the pin in Rwanda.');
        placeMarker(); // a dragged pin goes back to the last valid point
        return false;
      }
      value = next;
      say('');
      paintStatus();
      placeMarker(zoom === false ? 0 : (zoom || 17));
      if (opts.onChange) opts.onChange(value, meta || {});
      return true;
    }

    // ---- map
    if (global.L && typeof L.map === 'function') {
      try {
        map = L.map(mapEl, {
          scrollWheelZoom: false, tap: true,
          maxBounds: [[RWANDA.latMin - 0.3, RWANDA.lngMin - 0.3], [RWANDA.latMax + 0.3, RWANDA.lngMax + 0.3]],
          maxBoundsViscosity: 0.8, minZoom: 7
        });
        L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
          maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors'
        }).addTo(map);
        if (value) map.setView([value.lat, value.lng], 16); else map.setView(CENTER, 8);
        map.on('click', e => { if (!disabled) choose({ lat: e.latlng.lat, lng: e.latlng.lng }, { source: 'map' }, false); });
        placeMarker();
      } catch (e) { map = null; }
    }
    if (!map) {
      mapEl.replaceChildren(el('p', { class: 'lp-nomap', text: t('The map could not be loaded. Use your current location or search for the address.') }));
      hint.hidden = true;
    }

    // ---- current location (asked for only now)
    gps.addEventListener('click', () => {
      if (!navigator.geolocation) { say('This browser cannot share its location. Search for the address or place the pin on the map.'); return; }
      gps.disabled = true; say('');
      navigator.geolocation.getCurrentPosition(pos => {
        gps.disabled = disabled;
        if (choose({ lat: pos.coords.latitude, lng: pos.coords.longitude }, { source: 'gps', accuracy: pos.coords.accuracy }, 17)) {
          say(pos.coords.accuracy > 200 ? 'Your location is approximate. Check the pin and drag it to the exact place.' : '');
        }
      }, err => {
        gps.disabled = disabled;
        say(err && err.code === 1
          ? 'Location access was not allowed. Search for the address or place the pin on the map instead.'
          : 'Your location could not be read. Search for the address or place the pin on the map instead.');
      }, { enableHighAccuracy: true, timeout: 15000, maximumAge: 60000 });
    });

    // ---- address search (Nominatim: Rwanda only, at most one request per second)
    async function search() {
      const q = query.value.trim();
      results.hidden = true; results.replaceChildren();
      if (q.length < 3) { say('Type at least 3 characters of an address or place.'); return; }
      const wait = 1000 - (Date.now() - lastSearch);
      if (wait > 0) await new Promise(r => setTimeout(r, wait));
      lastSearch = Date.now();
      find.disabled = true; say('');
      try {
        const url = PLACES + '?' + new URLSearchParams({ format: 'jsonv2', countrycodes: 'rw', limit: '5', 'accept-language': lang, q });
        const res = await fetch(url, { headers: { Accept: 'application/json' } });
        if (!res.ok) throw new Error(String(res.status));
        const places = (await res.json()).filter(p => isFinite(p.lat) && isFinite(p.lon) && inRwanda({ lat: +p.lat, lng: +p.lon }));
        if (!places.length) { say('No place found in Rwanda. Try another name, or place the pin on the map.'); return; }
        results.replaceChildren(...places.map(p => {
          const b = el('button', { type: 'button', text: p.display_name });
          b.addEventListener('click', () => {
            results.hidden = true;
            choose({ lat: +p.lat, lng: +p.lon }, { source: 'search', address: p.display_name }, 17);
          });
          return el('li', {}, [b]);
        }));
        results.hidden = false;
        results.querySelector('button').focus();
      } catch (e) {
        say('The address search is not available right now. Place the pin on the map instead.');
      } finally { find.disabled = disabled; }
    }
    find.addEventListener('click', search);
    query.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); search(); } });
    clear.addEventListener('click', () => choose(null, { source: 'clear' }));

    paintStatus();
    return {
      get: () => (value ? { lat: value.lat, lng: value.lng } : null),
      set: v => choose(v && isFinite(v.lat) && isFinite(v.lng) ? { lat: +v.lat, lng: +v.lng } : null, { source: 'set' }, 16),
      // Leaflet measures its box when shown: call after a hidden form or dialog opens.
      refresh: () => { if (map) { map.invalidateSize(); if (value) map.setView([value.lat, value.lng], Math.max(map.getZoom(), 15)); } },
      disable: off => {
        disabled = !!off;
        [gps, query, find].forEach(x => { x.disabled = disabled; });
        if (marker && marker.dragging) { if (disabled) marker.dragging.disable(); else marker.dragging.enable(); }
        paintStatus();
      },
      inRwanda
    };
  }

  global.ApexLocationPicker = { mount, RWANDA };
})(window);
