'use strict';
/* Data for the dashboards. Both sources expose the same methods, so the screens
 * in dashboard.js do not care where the data comes from:
 *   DashData.live(role)    the ApexRX API (js/api.js)
 *   DashData.preview(role) sample data held in memory; nothing leaves the browser
 */
(function (global) {
  const OTHER = { pharmacy: 'supplier', supplier: 'pharmacy' };

  // The API caps a page at 100 rows.
  async function allPages(fetchPage, maxPages = 5) {
    const items = [];
    for (let page = 0; page < maxPages; page++) {
      const res = await fetchPage({ limit: 100, offset: page * 100 });
      items.push(...res.items);
      if (items.length >= res.total || !res.items.length) break;
    }
    return items;
  }

  // allowed_actions come as accept_counter; the URLs and the screens use accept-counter.
  const withActions = o => ({ ...o, allowed_actions: (o.allowed_actions || []).map(a => a.replace(/_/g, '-')) });

  /* ---------------------------------------------------------------- live */
  // The organization chosen for this tab, per role. Shared with js/registration.js
  // and js/accept-invitation.js, so every page opens the same organization.
  const ORG_KEYS = { pharmacy: 'apexrx_selected_pharmacy', supplier: 'apexrx_selected_supplier' };
  const savedOrg = r => { try { return sessionStorage.getItem(ORG_KEYS[r]); } catch (e) { return null; } };
  const rememberOrg = (r, id) => { try { sessionStorage.setItem(ORG_KEYS[r], String(id)); } catch (e) { /* storage unavailable */ } };

  // Background polls: no progress bar.
  const QUIET = { quiet: true };

  function live(role) {
    const A = global.ApexAPI;
    let orgId = null;
    const self = {
      preview: false,
      // The API has no stock batch routes yet: batch numbers and expiry dates are not stored.
      batches: false,
      async boot() {
        const me = await A.auth.me();
        const all = me.memberships || [];
        const mine = all.filter(m => m.organization_type === role);
        // The organization chosen in this tab, else the one the user owns, manages, or any.
        const m = mine.find(x => String(x.organization_id) === savedOrg(role))
          || mine.find(x => x.role === 'owner') || mine.find(x => x.role === 'manager') || mine[0];
        if (!m) {
          const other = all.find(x => x.organization_type === OTHER[role]);
          return { user: me, org: null, otherRole: other ? OTHER[role] : null };
        }
        orgId = m.organization_id;
        rememberOrg(role, orgId);
        const [org, locations] = await Promise.all([A.organizations.get(orgId), A.organizations.locations(orgId, { include_inactive: true })]);
        return { user: me, org, myRole: m.role, locations: locations || [], memberships: all };
      },
      // Switching organization: remember the choice; the page then reloads on it.
      choose: (r, id) => rememberOrg(r, id),
      refreshOrg: () => A.organizations.get(orgId),
      resubmit: () => A.organizations.resubmit(orgId),
      locations: () => A.organizations.locations(orgId, { include_inactive: true }),
      addLocation: data => A.organizations.createLocation(orgId, data),
      updateLocation: (id, data) => A.organizations.updateLocation(orgId, id, data),

      stock: locationId => allPages(p => A.inventory.list(orgId, { location_id: locationId, ...p })),
      setQuantity: (loc, product, qty, allowBelowReserved) => A.inventory.setQuantity(orgId, loc, product, qty, allowBelowReserved),
      setOffer: (loc, product, offer) => A.inventory.setOffer(orgId, loc, product, offer),
      removeOffer: (loc, product) => A.inventory.removeOffer(orgId, loc, product),
      removeStock: (loc, product) => A.inventory.remove(orgId, loc, product),
      confirmStock: loc => A.inventory.confirmLocation(orgId, loc),
      // No batch routes: only the quantity is saved. The screens hide batch fields
      // when `batches` is false, so nothing claims a batch was stored.
      setBatch: (loc, product, batch) => A.inventory.setQuantity(orgId, loc, product, batch.quantity),

      products: q => A.catalogue.products({ q, limit: 25 }).then(r => r.items),
      drugs: () => A.catalogue.drugs({ limit: 100 }).then(r => r.items),

      offers(params) {
        return A.supplierOffers.search({ pharmacy_organization_id: orgId, limit: 100, ...params }).then(r => r.items);
      },

      orders: () => allPages(p => A.purchaseOrders.list({ organization_id: orgId, ...p }), 3),
      order: id => A.purchaseOrders.get(id).then(withActions),
      // A quote request is a purchase order sent straight to the supplier.
      // Staff may prepare orders but only owners and managers send them: the
      // backend refuses the submit (403) and the order stays a draft, which is
      // reported as such ({ draft: true }), never as sent.
      async sendOrder({ supplierId, supplierLocationId, locationId, items, notes }) {
        const order = await A.purchaseOrders.create({
          pharmacy_organization_id: orgId, supplier_organization_id: supplierId,
          pharmacy_location_id: locationId, supplier_location_id: supplierLocationId || null,
          notes: notes || null, items
        });
        try { return await A.purchaseOrders.transition(order.purchase_order_id, 'submit'); } catch (err) {
          if (err.status === 403) return { ...order, draft: true };
          throw err;
        }
      },
      act: (id, action, body) => action === 'delete' ? A.purchaseOrders.remove(id) : A.purchaseOrders.transition(id, action, body),
      reprice: id => A.purchaseOrders.reprice(id),

      members: () => A.organizations.members(orgId),
      updateMember: (id, data) => A.organizations.updateMember(orgId, id, data),
      assignBranches: (id, locationIds) => A.organizations.assignBranches(orgId, id, locationIds),
      removeMember: id => A.organizations.removeMember(orgId, id),
      // Staff invitations (owners and managers). Email is temporarily disabled:
      // the backend then returns a single-use link for the inviter to share.
      invitations: () => A.invitations.list(orgId),
      invite: (email, r) => A.invitations.create(orgId, email, r),
      reinvite: id => A.invitations.resend(orgId, id),
      revokeInvite: id => A.invitations.revoke(orgId, id),
      capabilities: () => A.auth.capabilities().catch(() => ({ invitation_emails: false })),
      documents: () => A.organizations.documents(orgId),
      uploadDocument: (type, file) => A.organizations.uploadDocument(orgId, type, file),
      // Charts and management figures, computed by the API for owners and managers
      // only (staff get 403 there, whatever this page shows).
      insights: locationId => A.organizations.insights(orgId, locationId ? { location_id: locationId } : {}),

      // Messaging (stored in ApexRX; the page polls for new messages).
      orgId: () => orgId,
      // Pharmacies: the conversations of one branch (the one being viewed).
      conversations: (quiet, branchId) => A.conversations.list(orgId, quiet ? QUIET : undefined, branchId),
      startConversation: (otherId, branchId) => A.conversations.start(orgId, otherId, branchId),
      conversation: id => A.conversations.get(id, orgId),
      contacts: q => A.conversations.contacts(orgId, q),
      messages: (cid, params, quiet) => A.conversations.messages(cid, orgId, params, quiet ? QUIET : undefined),
      sendMessage: (cid, body) => A.conversations.send(cid, orgId, body),
      markRead: (cid, lastId) => A.conversations.read(cid, orgId, lastId),
      // Procurement requests and quotations.
      requests: quiet => A.procurement.list({ organization_id: orgId, limit: 100 }, quiet ? QUIET : undefined).then(r => r.items),
      request: id => A.procurement.get(id),
      createRequest: ({ supplierId, locationId, notes, neededBy, items }) => A.procurement.create({
        pharmacy_organization_id: orgId, supplier_organization_id: supplierId, pharmacy_location_id: locationId,
        notes: notes || null, needed_by: neededBy || null, items
      }),
      viewedRequest: id => A.procurement.viewed(id),
      quote: (id, body) => A.procurement.quote(id, body),
      requestAct(id, action, body, quotationId) {
        if (action === 'decline') return A.procurement.decline(id, body.reason);
        if (action === 'cancel') return A.procurement.cancel(id, body.reason);
        if (action === 'convert') return A.procurement.convert(id, body);
        return A.procurement.answer(id, quotationId, action.replace(/_/g, '-'), body);
      },
      // Patient reservations (pharmacies; js/dashboard-reservations.js).
      reservations: (params, quiet) => A.pharmacyReservations.list(orgId, params, quiet ? QUIET : undefined),
      reservation: (ref, quiet) => A.pharmacyReservations.get(orgId, ref, quiet ? QUIET : undefined),
      reservationAct: (ref, action, body) => A.pharmacyReservations.act(orgId, ref, action, body),
      reservationMedicines: (loc, params) => A.pharmacyReservations.medicines(orgId, loc, params),
      reservationSettings: product => A.pharmacyReservations.settings(product),
      notifications: quiet => A.notifications.list(orgId, { limit: 30 }, quiet ? QUIET : undefined),
      readNotifications: ids => A.notifications.read(orgId, ids),
      signOut: () => A.auth.logout()
    };
    return self;
  }

  /* ------------------------------------------------------------- preview */
  const iso = (days = 0) => new Date(Date.now() + days * 864e5).toISOString();
  const CAT = [
    [1, 'Amoxicillin', 'Antibiotic', 'Amoxicillin 500mg', '500mg', 'B/20 Capsules'],
    [2, 'Ciprofloxacin', 'Antibiotic', 'Ciprofloxacin 500mg', '500mg', 'B/10 Tablets'],
    [3, 'Paracetamol', 'Analgesic / antipyretic', 'Paracetamol 500mg', '500mg', 'B/30 Tablets'],
    [4, 'Ibuprofen', 'NSAID', 'Ibuprofen 400mg', '400mg', 'B/30 Tablets'],
    [5, 'Metformin', 'Antidiabetic', 'Metformin 500mg', '500mg', 'B/60 Tablets'],
    [6, 'Insulin Glargine', 'Antidiabetic', 'Insulin Glargine 100IU/ml', '100IU/ml', 'B/1 Pen'],
    [7, 'Amlodipine', 'Antihypertensive', 'Amlodipine 5mg', '5mg', 'B/30 Tablets'],
    [8, 'Enalapril', 'Antihypertensive', 'Enalapril 10mg', '10mg', 'B/30 Tablets'],
    [9, 'Albendazole', 'Anthelmintic', 'Albendazole 400mg', '400mg', 'B/2 Tablets'],
    [10, 'Artemether/Lumefantrine', 'Antimalarial', 'Artemether/Lumefantrine 20/120mg', '20/120mg', 'B/24 Tablets'],
    [11, 'Cetirizine', 'Antihistamine', 'Cetirizine 10mg', '10mg', 'B/30 Tablets'],
    [12, 'Salbutamol', 'Bronchodilator', 'Salbutamol 100mcg', '100mcg', 'B/1 Inhaler'],
    [13, 'ORS', 'Rehydration', 'ORS', null, 'B/25 Sachets']
  ].map(([id, drug, cls, name, strength, pack]) => ({ product_id: id, drug_id: id, drug_name: drug, therapeutic_class: cls, product_name: name, strength, pack_size: pack, dosage_form: null }));
  const P = id => CAT.find(c => c.product_id === id);
  const SUPPLIERS = {
    4: { name: 'PharmaRwanda Wholesale', loc: 41, location: 'Nyarugenge depot', city: 'Nyarugenge', lat: -1.9441, lng: 30.0619, phone: '+250788000104' },
    5: { name: 'Kigali Medical Wholesalers', loc: 51, location: 'Gikondo depot', city: 'Kicukiro', lat: -1.978, lng: 30.078, phone: '+250788000105' },
    6: { name: 'AfriPharma Supply', loc: 61, location: 'Kimironko depot', city: 'Gasabo', lat: -1.949, lng: 30.126, phone: '+250788000106' }
  };
  const PHARMACIES = {
    1: { name: 'Demo Pharmacy Kacyiru', loc: 11, location: 'Kacyiru (main)', phone: '+250788000201' },
    2: { name: 'Demo Pharmacy Remera', loc: 12, location: 'Remera', phone: '+250788000202' }
  };
  const OFFER_ROWS = [[4,1,3100],[5,1,3300],[6,1,3000],[4,2,2600],[5,2,2750],[4,3,1700],[5,3,1650],[5,4,2000],[6,4,1950],[4,5,2400],[6,5,2350],[6,6,16500],[4,6,17200],[6,7,2100],[4,7,2200],[5,7,2150],[4,8,1900],[5,8,1850],[4,9,900],[5,9,850],[6,9,880],[4,10,2800],[6,10,2700],[4,11,1100],[5,11,1050],[5,12,3900],[6,12,3800],[4,13,400],[5,13,380]];
  const km = (a, b, c, d) => { const r = Math.PI / 180, h = Math.sin((c - a) * r / 2) ** 2 + Math.cos(a * r) * Math.cos(c * r) * Math.sin((d - b) * r / 2) ** 2; return 12742 * Math.asin(Math.sqrt(h)); };

  function preview(role) {
    let seq = 9000;
    const pharmacy = role === 'pharmacy';
    const org = pharmacy
      ? { organization_id: 1, name: 'Demo Pharmacy Kacyiru', type: 'pharmacy', status: 'approved', phone: '+250 788 123 456', email: 'pharmacy@example.com' }
      : { organization_id: 4, name: 'PharmaRwanda Wholesale', type: 'supplier', status: 'approved', phone: '+250 788 123 456', email: 'depot@example.com' };
    const locations = pharmacy
      ? [{ location_id: 11, name: 'Kacyiru (main)', city: 'Gasabo', region: 'Kigali', address: 'KG 7 Ave, Kacyiru', latitude: -1.9355, longitude: 30.0912, phone: '+250788000201', is_active: true },
         { location_id: 12, name: 'Remera', city: 'Gasabo', region: 'Kigali', address: 'KG 11 Ave, Remera', latitude: -1.9536, longitude: 30.1044, phone: '+250788000202', is_active: true }]
      : [{ location_id: 41, name: 'Main depot', city: 'Nyarugenge', region: 'Kigali', address: 'KN 2 St, Kivugiza', latitude: -1.9441, longitude: 30.0619, phone: '+250788000104', is_active: true }];
    const day = n => iso(n).slice(0, 10);
    const expiredOf = s => s.batches.filter(b => b.expiry_date < day(0)).reduce((t, b) => t + b.quantity, 0);
    const refresh = s => {
      s.batches.sort((a, b) => a.expiry_date.localeCompare(b.expiry_date));
      s.batches.forEach(b => { b.is_expired = b.expiry_date < day(0); });
      if (s.batches.length) s.quantity = s.batches.reduce((t, b) => t + b.quantity, 0);
      s.expired_quantity = expiredOf(s); s.last_updated = iso();
      return { ...s, availability_status: availability(s) };
    };
    // batches: [number, days until expiry, boxes]
    const row = (loc, id, batches, price, threshold, listed, days) => {
      const p = P(id), l = locations.find(x => x.location_id === loc);
      const list = (Array.isArray(batches) ? batches : []).map(([n, left, q]) => ({ batch_id: ++seq, batch_number: n, expiry_date: day(left), quantity: q, is_expired: left < 0 }));
      const qty = Array.isArray(batches) ? list.reduce((t, b) => t + b.quantity, 0) : batches;
      return { batches: list, expired_quantity: list.filter(b => b.is_expired).reduce((t, b) => t + b.quantity, 0), stock_id: ++seq, location_id: loc, location_name: l.name, product_id: id, product_name: p.product_name, drug_id: id, drug_name: p.drug_name, brand: null, strength: p.strength, dosage_form: null, pack_size: p.pack_size, quantity: qty, last_updated: iso(-days), updated_by: null,
        offer: price == null ? null : { offer_id: ++seq, unit_price: price, currency: 'RWF', low_stock_threshold: threshold, is_listed: listed, last_updated: iso(-days), updated_by: null } };
    };
    const stock = pharmacy
      ? [row(11,1,[['AMX2401',420,25],['AMX2312',60,15]],4500,10,true,2), row(11,3,[['PCM2405',300,200]],2500,20,true,2), row(11,5,[['MET2402',75,6]],3500,10,true,5), row(11,7,[['AML2403',500,55]],3000,10,true,7), row(11,6,[['INS2401',150,3]],22000,5,true,3), row(11,11,[['CET2310',-20,15]],2200,5,true,14), row(12,3,[['PCM2406',280,120]],2400,20,true,1), row(12,13,[['ORS2404',200,90]],1500,10,true,1), row(12,9,[['ALB2405',250,40]],1000,10,true,3)]
      : [row(41,1,[['AMX-W2401',400,2000],['AMX-W2312',60,300]],3100,100,true,2), row(41,3,[['PCM-W2402',500,5000]],1700,100,true,2), row(41,5,[['MET-W2403',75,80]],2400,100,true,7), row(41,11,[['CET-W2309',-10,120]],1100,100,true,21)];
    const availability = s => { const q = s.quantity - (s.expired_quantity || 0); return !s.offer || !s.offer.is_listed ? null : q <= 0 ? 'unavailable' : q <= s.offer.low_stock_threshold ? 'low_stock' : 'in_stock'; };

    const party = (kind, id, locId) => {
      const x = kind === 'supplier' ? SUPPLIERS[id] : PHARMACIES[id];
      return { organization_id: id, name: x.name, location_id: locId || x.loc, location_name: x.location, phone: x.phone, whatsapp_phone: x.phone };
    };
    const actionsFor = o => {
      const map = pharmacy
        ? { submitted: ['cancel'], countered: ['accept-counter', 'cancel'], accepted: ['cancel'], dispatched: ['mark-delivered'] }
        : { submitted: ['accept', 'counter', 'reject'], accepted: ['start-processing', 'dispatch', 'cancel'], processing: ['dispatch', 'cancel'], dispatched: ['mark-delivered'] };
      return map[o.status] || [];
    };
    const lineTotals = o => {
      o.requested_total = o.items.reduce((t, i) => t + i.requested_line_total, 0);
      const confirmed = o.items.filter(i => i.confirmed_unit_price != null);
      o.confirmed_total = confirmed.length ? confirmed.reduce((t, i) => t + i.confirmed_line_total, 0) : null;
      o.item_count = o.items.length;
      o.allowed_actions = actionsFor(o);
      return o;
    };
    const makeOrder = (id, status, sup, ph, lines, hours, extraHistory = []) => {
      const created = iso(-hours / 24);
      const items = lines.map(([pid, qty, price, cQty, cPrice], n) => {
        const p = P(pid);
        return { purchase_order_item_id: id * 10 + n, product_id: pid, product_name: p.product_name, drug_name: p.drug_name, strength: p.strength, dosage_form: null, pack_size: p.pack_size, requested_quantity: qty, requested_unit_price: price, confirmed_quantity: cQty ?? null, confirmed_unit_price: cPrice ?? null, requested_line_total: qty * price, confirmed_line_total: cQty != null ? cQty * cPrice : null };
      });
      return lineTotals({ purchase_order_id: id, status, currency: 'RWF', pharmacy: party('pharmacy', ph), supplier: party('supplier', sup), items, notes: null, rejection_reason: null, created_at: created, updated_at: created, submitted_at: created, responded_at: null,
        history: [{ history_id: id * 10, from_status: 'draft', to_status: 'submitted', changed_by_name: 'Alice', changed_at: created, note: null }, ...extraHistory] });
    };
    const orders = pharmacy
      ? [makeOrder(1001, 'countered', 4, 1, [[1,200,3100,200,2900],[3,100,1700,100,1650],[5,50,2400,50,2300]], 6, [{ history_id: 1, from_status: 'submitted', to_status: 'countered', changed_by_name: 'Diane', changed_at: iso(-.2), note: 'Better price for this volume. Valid for 7 days.' }])]
      : [makeOrder(2001, 'submitted', 4, 1, [[1,200,3100],[3,100,1700],[5,50,2400]], 3), makeOrder(2002, 'submitted', 4, 2, [[3,300,1700]], 5)];

    /* Messaging and procurement in the preview: the same shapes and rules as
     * the API, held in memory. The sample counterpart never answers by itself. */
    const other = pharmacy
      ? { organization_id: 4, name: SUPPLIERS[4].name, type: 'supplier', city: SUPPLIERS[4].city, phone: SUPPLIERS[4].phone }
      : { organization_id: 1, name: PHARMACIES[1].name, type: 'pharmacy', city: 'Gasabo', phone: PHARMACIES[1].phone };
    const contactList = pharmacy
      ? Object.entries(SUPPLIERS).map(([id, x]) => ({ organization_id: +id, name: x.name, type: 'supplier', city: x.city, phone: x.phone }))
      : Object.entries(PHARMACIES).map(([id, x]) => ({ organization_id: +id, name: x.name, type: 'pharmacy', city: 'Gasabo', phone: x.phone }));
    const convs = [{ conversation_id: 1, organization_id: org.organization_id, counterpart: other, created_at: iso(-2), last_message_at: iso(-0.05) }];
    const msgs = [
      { message_id: 1, conversation_id: 1, sender_organization_id: 1, sender_name: 'Alice', body: 'Hello, do you have Amoxicillin 500mg for next week?', created_at: iso(-0.1) },
      { message_id: 2, conversation_id: 1, sender_organization_id: 4, sender_name: 'Diane', body: 'Yes, we have it. Send us a request with the quantities and we will quote.', created_at: iso(-0.05) }
    ];
    const reads = { 1: pharmacy ? 1 : 2 };
    const msgOut = m => ({ ...m, sender_user_id: null, mine: m.sender_organization_id === org.organization_id });
    const convOut = c => {
      const list = msgs.filter(m => m.conversation_id === c.conversation_id), last = list[list.length - 1];
      const unread = list.filter(m => !msgOut(m).mine && m.message_id > (reads[c.conversation_id] || 0)).length;
      return { ...c, last_message: last ? msgOut(last) : null, unread_count: unread };
    };
    const ph1 = { organization_id: 1, name: PHARMACIES[1].name, location_id: 11, location_name: PHARMACIES[1].location };
    const sup4 = { organization_id: 4, name: SUPPLIERS[4].name, location_id: null, location_name: null };
    const reqItem = (id, line, name, extra, qty, pid) => ({ procurement_request_item_id: id, line_no: line, product_id: pid || null, in_catalogue: !!pid, medicine_name: name, strength: extra[0] || null, dosage_form: extra[1] || null, pack_size: extra[2] || null, quantity: qty, notes: null });
    const requests = [{
      procurement_request_id: 501, status: pharmacy ? 'quoted' : 'submitted', pharmacy: ph1, supplier: sup4, conversation_id: 1, currency: 'RWF',
      notes: 'For the Kacyiru branch. Delivery before Friday if possible.', needed_by: day(7), status_reason: null, created_by_name: 'Alice', viewed_at: null,
      created_at: iso(-1), updated_at: iso(-0.5), purchase_order_id: null,
      items: [reqItem(5011, 1, 'Amoxicillin 500mg', ['500mg', null, 'B/20 Capsules'], 100, 1), reqItem(5012, 2, 'Artemether/Lumefantrine suspension', ['180/1080mg', 'suspension', '60ml'], 30)],
      quotations: pharmacy ? [{ quotation_id: 601, revision: 1, status: 'submitted', currency: 'RWF', note: 'Prices valid for 7 days.', estimated_days: 2, submitted_by_name: 'Diane', submitted_at: iso(-0.5), responded_by_name: null, responded_at: null, response_note: null, updated_at: iso(-0.5),
        items: [{ quotation_item_id: 6011, procurement_request_item_id: 5011, available: true, quantity: 100, unit_price: 3000, note: null }, { quotation_item_id: 6012, procurement_request_item_id: 5012, available: false, quantity: null, unit_price: null, note: 'Back in stock next month' }] }] : []
    }];
    const qTotal = q => q.items.filter(i => i.available).reduce((t, i) => t + i.quantity * i.unit_price, 0);
    const reqOut = r => {
      const shown = r.quotations.filter(q => !pharmacy || q.status !== 'draft'), latest = shown[shown.length - 1];
      const st = r.status, acts = [];
      if (!pharmacy) { if (['submitted', 'viewed', 'quoted', 'negotiation'].includes(st)) acts.push('quote'); if (['submitted', 'viewed', 'negotiation'].includes(st)) acts.push('decline'); }
      else {
        if (st === 'quoted' && latest && latest.status === 'submitted') acts.push('request_revision', 'accept', 'reject');
        if (st === 'accepted') acts.push('convert');
        if (['submitted', 'viewed', 'quoted', 'negotiation', 'accepted'].includes(st)) acts.push('cancel');
      }
      return { ...r, item_count: r.items.length, latest_quotation_status: latest ? latest.status : null, latest_quotation_total: latest ? qTotal(latest) : null,
        needs_my_action: pharmacy ? ['quoted', 'accepted'].includes(st) : ['submitted', 'viewed', 'negotiation'].includes(st),
        quotations: shown.map(q => ({ ...q, total: qTotal(q), items: q.items.map(i => ({ ...i, line_total: i.available ? i.quantity * i.unit_price : null })) })), allowed_actions: acts };
    };
    const findReq = id => requests.find(r => r.procurement_request_id === +id);
    const notes = [{ notification_id: 1, kind: pharmacy ? 'quotation_submitted' : 'request_submitted', from_organization_id: other.organization_id, from_organization_name: other.name, conversation_id: 1, procurement_request_id: 501, quotation_id: pharmacy ? 601 : null, purchase_order_id: null, created_at: iso(-0.5), read: false }];
    const touch = r => { r.updated_at = iso(); };
    const delay = v => new Promise(r => setTimeout(() => r(typeof structuredClone === 'function' ? structuredClone(v) : JSON.parse(JSON.stringify(v))), 60));
    const find = id => orders.find(o => o.purchase_order_id === +id);
    const members = [{ membership_id: 1, user_id: 0, name: 'Alice', email: 'alice@example.com', role: 'owner', is_active: true }, { membership_id: 2, user_id: 2, name: 'Eric', email: 'eric@example.com', role: 'manager', is_active: true }, { membership_id: 3, user_id: 3, name: 'Grace', email: 'grace@example.com', role: 'staff', is_active: true }];
    const documents = [];
    const STATUS_AFTER = { accept: 'accepted', 'accept-counter': 'accepted', reject: 'rejected', cancel: 'cancelled', 'start-processing': 'processing', dispatch: 'dispatched', 'mark-delivered': 'delivered', submit: 'submitted', counter: 'countered' };

    return {
      preview: true,
      batches: true,
      boot: () => delay({ user: { user_id: 0, name: 'Alice', email: org.email }, org, myRole: 'owner', locations, memberships: [] }),
      choose() {},
      refreshOrg: () => delay(org),
      resubmit: () => delay(org),
      locations: () => delay(locations),
      addLocation(data) { const l = { ...data, location_id: ++seq, is_active: true }; locations.push(l); return delay(l); },
      updateLocation(id, data) { Object.assign(locations.find(l => l.location_id === id), data); return delay(null); },
      stock: loc => delay(stock.filter(s => s.location_id === loc).map(s => ({ ...s, availability_status: availability(s) }))),
      setQuantity(loc, pid, qty) {
        let s = stock.find(x => x.location_id === loc && x.product_id === pid);
        if (!s) { s = row(loc, pid, 0, null, 5, true, 0); stock.push(s); }
        s.quantity = qty; s.last_updated = iso();
        return delay(s);
      },
      setBatch(loc, pid, batch) {
        let s = stock.find(x => x.location_id === loc && x.product_id === pid);
        if (!s) { s = row(loc, pid, [], null, 5, true, 0); stock.push(s); }
        const same = s.batches.find(b => b.batch_number.toLowerCase() === batch.batch_number.toLowerCase());
        if (same) Object.assign(same, batch); else s.batches.push({ batch_id: ++seq, ...batch });
        return delay(refresh(s));
      },
      updateBatch(loc, pid, id, body) {
        const s = stock.find(x => x.location_id === loc && x.product_id === pid);
        Object.assign(s.batches.find(b => b.batch_id === id), body);
        return delay(refresh(s));
      },
      removeBatch(loc, pid, id) {
        const s = stock.find(x => x.location_id === loc && x.product_id === pid);
        s.batches = s.batches.filter(b => b.batch_id !== id);
        if (!s.batches.length) s.quantity = 0;
        return delay(refresh(s));
      },
      setOffer(loc, pid, offer) {
        const s = stock.find(x => x.location_id === loc && x.product_id === pid);
        s.offer = { offer_id: ++seq, currency: 'RWF', last_updated: iso(), updated_by: null, ...offer };
        return delay(s);
      },
      removeOffer(loc, pid) { stock.find(x => x.location_id === loc && x.product_id === pid).offer = null; return delay(null); },
      removeStock(loc, pid) { stock.splice(stock.findIndex(x => x.location_id === loc && x.product_id === pid), 1); return delay(null); },
      confirmStock(loc) { stock.filter(s => s.location_id === loc).forEach(s => s.last_updated = iso()); return delay(null); },
      products(q) { const w = q.toLowerCase(); return delay(CAT.filter(c => (c.product_name + ' ' + c.drug_name).toLowerCase().includes(w))); },
      drugs: () => delay(CAT.map(c => ({ drug_id: c.drug_id, name: c.drug_name, therapeutic_class: c.therapeutic_class }))),
      offers({ q, drug_id, supplier_organization_id, lat, lng, sort }) {
        const w = (q || '').toLowerCase();
        const res = OFFER_ROWS.map(([sid, pid, price], n) => {
          const p = P(pid), s = SUPPLIERS[sid];
          return { offer_id: n + 1, product_id: pid, product_name: p.product_name, drug_id: pid, drug_name: p.drug_name, strength: p.strength, dosage_form: null, pack_size: p.pack_size, supplier_organization_id: sid, supplier_name: s.name, supplier_location_id: s.loc, location_name: s.location, city: s.city, latitude: s.lat, longitude: s.lng, phone: s.phone, whatsapp_phone: s.phone, whatsapp_url: 'https://wa.me/' + s.phone.replace(/\D/g, ''), unit_price: price, currency: 'RWF', quantity: 40 + (n * 37) % 400, last_updated: iso(-1), distance_km: lat != null ? +km(lat, lng, s.lat, s.lng).toFixed(2) : null };
        }).filter(o => (!w || (o.product_name + ' ' + o.drug_name).toLowerCase().includes(w)) && (!drug_id || o.drug_id === drug_id) && (!supplier_organization_id || o.supplier_organization_id === supplier_organization_id));
        res.sort((a, b) => sort === 'distance' ? a.distance_km - b.distance_km : a.unit_price - b.unit_price);
        return delay(res);
      },
      orders: () => delay(orders.slice().sort((a, b) => b.updated_at.localeCompare(a.updated_at))),
      order: id => delay(find(id)),
      sendOrder({ supplierId, locationId, items, notes }) {
        const id = ++seq;
        const lines = items.map(i => {
          const r = OFFER_ROWS.find(([s, p]) => s === supplierId && p === i.product_id);
          return [i.product_id, i.quantity, r ? r[2] : 0];
        });
        const o = makeOrder(id, 'submitted', supplierId, 1, lines, 0);
        o.notes = notes || null; o.pharmacy.location_id = locationId;
        orders.unshift(o);
        // The sample supplier answers on its own, so the whole flow can be tried.
        setTimeout(() => {
          o.items.forEach(i => { i.confirmed_quantity = i.requested_quantity; i.confirmed_unit_price = Math.round(i.requested_unit_price * .97 / 10) * 10; i.confirmed_line_total = i.confirmed_quantity * i.confirmed_unit_price; });
          o.status = 'countered'; o.updated_at = iso();
          o.history.push({ history_id: ++seq, from_status: 'submitted', to_status: 'countered', changed_by_name: 'Sample supplier', changed_at: iso(), note: 'Automatic sample reply.' });
          lineTotals(o);
          global.dispatchEvent(new CustomEvent('apexrx:preview-update', { detail: 'New price offer from ' + o.supplier.name }));
        }, 1800);
        return delay(o);
      },
      act(id, action, body = {}) {
        if (action === 'delete') { orders.splice(orders.indexOf(find(id)), 1); return delay(null); }
        const o = find(id);
        if (action === 'counter') body.items.forEach(c => {
          const i = o.items.find(x => x.purchase_order_item_id === c.purchase_order_item_id);
          i.confirmed_quantity = c.confirmed_quantity; i.confirmed_unit_price = c.confirmed_unit_price; i.confirmed_line_total = c.confirmed_quantity * c.confirmed_unit_price;
        });
        if (action === 'accept') o.items.forEach(i => { i.confirmed_quantity = i.requested_quantity; i.confirmed_unit_price = i.requested_unit_price; i.confirmed_line_total = i.requested_line_total; });
        const before = o.status;
        o.status = STATUS_AFTER[action]; o.updated_at = iso();
        if (action === 'reject' || action === 'cancel') o.rejection_reason = body.reason;
        o.history.push({ history_id: ++seq, from_status: before, to_status: o.status, changed_by_name: 'Alice', changed_at: iso(), note: body.note || body.reason || null });
        lineTotals(o);
        return delay(o);
      },
      reprice: () => delay([]),
      members: () => delay(members),
      updateMember(id, data) { Object.assign(members.find(m => m.membership_id === id), data); return delay(null); },
      removeMember(id) { members.splice(members.findIndex(m => m.membership_id === id), 1); return delay(null); },
      // Invitations create real sign-in links, so the preview never makes one.
      invitations: () => delay([]),
      capabilities: () => delay({ invitation_emails: false }),
      documents: () => delay(documents),
      uploadDocument(type, file) { const d = { document_id: ++seq, document_type: type, file_name: file.name, verification_status: 'pending' }; documents.push(d); return delay(d); },
      // Same shape and rules as GET /organizations/{id}/insights, from the sample data.
      insights(loc) {
        const health = { in_stock: 0, low_stock: 0, out_of_stock: 0, total: 0 };
        stock.filter(s => !loc || s.location_id === loc).forEach(s => {
          const q = s.quantity - (s.expired_quantity || 0), thr = s.offer ? s.offer.low_stock_threshold : 5;
          health[q <= 0 ? 'out_of_stock' : q <= thr ? 'low_stock' : 'in_stock']++; health.total++;
        });
        const pipeline = {};
        ['draft', 'submitted', 'countered', 'accepted', 'rejected', 'processing', 'dispatched', 'delivered', 'cancelled'].filter(st => pharmacy || st !== 'draft').forEach(st => { pipeline[st] = orders.filter(o => o.status === st).length; });
        const open = orders.filter(o => ['submitted', 'countered', 'accepted', 'processing', 'dispatched'].includes(o.status));
        const by = new Map();
        orders.filter(o => o.status !== 'draft').slice().sort((a, b) => b.created_at.localeCompare(a.created_at)).slice(0, 15)
          .forEach(o => o.items.forEach(i => { const c = by.get(i.product_id) || { product_id: i.product_id, product_name: i.product_name, drug_name: i.drug_name, strength: i.strength, pack_size: i.pack_size, quantity: 0 }; c.quantity += i.confirmed_quantity ?? i.requested_quantity; by.set(i.product_id, c); }));
        return delay({ organization_id: org.organization_id, location_id: loc || null, stock_health: health, order_pipeline: pipeline,
          open_order_value: open.reduce((v, o) => v + Number(o.confirmed_total ?? o.requested_total ?? 0), 0), currency: 'RWF',
          top_requested: [...by.values()].sort((a, b) => b.quantity - a.quantity || a.product_name.localeCompare(b.product_name)).slice(0, 5) });
      },
      conversations: () => delay({ items: convs.map(convOut).sort((a, b) => (b.last_message_at || b.created_at).localeCompare(a.last_message_at || a.created_at)), unread_total: convs.map(convOut).reduce((n, c) => n + c.unread_count, 0) }),
      startConversation(otherId) {
        let c = convs.find(x => x.counterpart.organization_id === +otherId);
        if (!c) { c = { conversation_id: ++seq, organization_id: org.organization_id, counterpart: contactList.find(x => x.organization_id === +otherId), created_at: iso(), last_message_at: null }; convs.push(c); }
        return delay(convOut(c));
      },
      contacts: q => delay(contactList.filter(c => !q || c.name.toLowerCase().includes(q.toLowerCase()))),
      conversation: id => delay(convOut(convs.find(c => c.conversation_id === +id))),
      messages(cid, params = {}) {
        const list = msgs.filter(m => m.conversation_id === +cid && (!params.after_id || m.message_id > params.after_id));
        return delay({ items: list.map(msgOut), has_more: false, last_read_message_id: reads[cid] || null });
      },
      sendMessage(cid, body) {
        const m = { message_id: ++seq, conversation_id: +cid, sender_organization_id: org.organization_id, sender_name: 'Alice', body: body.trim(), created_at: iso() };
        msgs.push(m); reads[cid] = m.message_id; convs.find(c => c.conversation_id === +cid).last_message_at = m.created_at;
        return delay(msgOut(m));
      },
      markRead(cid, lastId) { reads[cid] = Math.max(reads[cid] || 0, lastId); notes.filter(n => n.kind === 'message' && n.conversation_id === +cid).forEach(n => { n.read = true; }); return delay(null); },
      requests: () => delay(requests.map(reqOut).sort((a, b) => b.created_at.localeCompare(a.created_at))),
      request: id => delay(reqOut(findReq(id))),
      createRequest({ supplierId, notes: text, neededBy, items, locationId }) {
        const sup = contactList.find(c => c.organization_id === +supplierId) || other;
        let c = convs.find(x => x.counterpart.organization_id === sup.organization_id);
        if (!c) { c = { conversation_id: ++seq, organization_id: org.organization_id, counterpart: sup, created_at: iso(), last_message_at: null }; convs.push(c); }
        const r = { procurement_request_id: ++seq, status: 'submitted', pharmacy: { ...ph1, location_id: locationId }, supplier: { organization_id: sup.organization_id, name: sup.name, location_id: null, location_name: null }, conversation_id: c.conversation_id, currency: 'RWF', notes: text || null, needed_by: neededBy || null, status_reason: null, created_by_name: 'Alice', viewed_at: null, created_at: iso(), updated_at: iso(), purchase_order_id: null,
          items: items.map((i, n) => { const p = i.product_id ? P(i.product_id) : null; return reqItem(++seq, n + 1, p ? p.product_name : i.medicine_name, p ? [p.strength, null, p.pack_size] : [i.strength, i.dosage_form, i.pack_size], i.quantity, i.product_id); }), quotations: [] };
        requests.unshift(r);
        return delay(reqOut(r));
      },
      viewedRequest(id) { const r = findReq(id); if (!pharmacy && r.status === 'submitted') { r.status = 'viewed'; r.viewed_at = iso(); } return delay(reqOut(r)); },
      quote(id, body) {
        const r = findReq(id);
        let q = r.quotations.find(x => x.status === 'draft');
        if (!q) { q = { quotation_id: ++seq, revision: r.quotations.length + 1, status: 'draft', currency: 'RWF', submitted_by_name: null, submitted_at: null, responded_by_name: null, responded_at: null, response_note: null }; r.quotations.push(q); }
        Object.assign(q, { note: body.note || null, estimated_days: body.estimated_days ?? null, updated_at: iso(), items: body.items.map(i => ({ quotation_item_id: ++seq, ...i, quantity: i.available ? i.quantity : null, unit_price: i.available ? i.unit_price : null })) });
        if (body.submit) {
          r.quotations.forEach(x => { if (x !== q && ['submitted', 'revision_requested'].includes(x.status)) x.status = 'superseded'; });
          Object.assign(q, { status: 'submitted', submitted_by_name: 'Alice', submitted_at: iso() }); r.status = 'quoted';
        }
        touch(r);
        return delay(reqOut(r));
      },
      requestAct(id, action, body = {}, qid) {
        const r = findReq(id), q = r.quotations.find(x => x.quotation_id === +qid);
        const answer = st => Object.assign(q, { status: st, responded_by_name: 'Alice', responded_at: iso(), response_note: body.note || body.reason || null });
        if (action === 'request_revision') { answer('revision_requested'); r.status = 'negotiation'; }
        if (action === 'accept') { answer('accepted'); r.status = 'accepted'; }
        if (action === 'reject') { answer('rejected'); r.status = 'rejected'; r.status_reason = body.reason; }
        if (action === 'decline' || action === 'cancel') { r.status = action === 'decline' ? 'rejected' : 'cancelled'; r.status_reason = body.reason; }
        touch(r);
        if (action === 'convert') {
          // The sample order mirrors what the API creates: accepted, at the quoted terms.
          const acc = r.quotations.find(x => x.status === 'accepted');
          const lines = acc.items.filter(i => i.available).map(i => { const it = r.items.find(x => x.procurement_request_item_id === i.procurement_request_item_id); return [it.product_id || 3, i.quantity, i.unit_price, i.quantity, i.unit_price]; });
          const o = makeOrder(++seq, 'accepted', r.supplier.organization_id, 1, lines, 0);
          o.procurement_request_id = r.procurement_request_id; o.quotation_id = acc.quotation_id;
          orders.unshift(o); r.status = 'converted'; r.purchase_order_id = o.purchase_order_id;
          return delay({ purchase_order_id: o.purchase_order_id, created: true, request: reqOut(r) });
        }
        return delay(reqOut(r));
      },
      notifications: () => delay({ items: notes.slice(), unread_count: notes.filter(n => !n.read).length }),
      readNotifications(ids) { notes.filter(n => !ids || ids.includes(n.notification_id)).forEach(n => { n.read = true; }); return delay(null); },
      orgId: () => org.organization_id,
      signOut() {}
    };
  }

  global.DashData = { live, preview };
})(window);
