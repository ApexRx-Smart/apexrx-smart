# Plan: in-platform messaging and pharmacy-to-supplier procurement requests

Branch: `feature/messaging-procurement`, from `main` at 1ffe71f.

## What existed (inspected first)
- **Messages screen** (`frontend/js/dashboard.js`): a view over purchase orders, one thread per counterpart, built from their orders. Typed text was not stored: **Send on WhatsApp** opened `wa.me` in a new tab. No unread state.
- **Purchase orders**: complete workflow with database triggers (draft, submitted, countered, accepted, processing, dispatched, delivered). Every line needs a catalogue product, prices come from the supplier's listing, and orders must be inserted as drafts.
- **Catalogue**: admin-only writes. **Notifications**: none in-app. **Real-time**: none; the dashboard already polls orders. **Rate limiting**: the `limits` library, used for sign-in.
- **Other branches**: `feature/database-schema` has an unmerged SQL draft of `conversation`, `message` and `quote` tables, never wired to the backend; its rules were reused (one conversation per pharmacy and supplier pair, verified organizations, sender organization and user on each message). `feature/pharmworkflow-implementation` has a demo chat with hard-coded sample suppliers (nothing reusable). No branch had procurement requests, quotations or notifications.

## Changes
- **Migration `b7c3e9d1f4a6`** (additive):
  - `conversation` (unique pair), `message` (immutable, sender must belong to the conversation: trigger), `conversation_read`;
  - `procurement_request`, `procurement_request_item` (catalogue product or free-text description);
  - `quotation` (numbered revisions; at most one open and one accepted per request), `quotation_item` (sent quotations immutable: trigger);
  - `notification`, `notification_read`;
  - `purchase_order.procurement_request_id` and `quotation_id` (unique), `purchase_order_item.product_id` optional plus `item_description`.
- **Backend**: `app/api/messaging.py` (`/conversations`, `/notifications`), `app/api/procurement.py` (`/procurement-requests`), `app/services/messaging.py`, `app/services/procurement.py`; order responses handle lines outside the catalogue and show the request and quotation references. Rate limits: 30 messages a minute and 30 requests an hour per user.
- **Conversion**: reuses the order workflow (draft, then submitted, then accepted at the quoted terms), under a row lock on the request; a repeated call returns the same order.
- **Frontend**: Messages stores and shows real messages (WhatsApp send replaced), with orders and requests in the same thread; new Procurement requests screen on both dashboards; notification bell; polling (5 s for the open chat, 20 s for lists and notifications). Text in English, French and Kinyarwanda.

## Not changed
Existing order routes and rules, Compare prices **Ask for quote** (still creates an order from a listed price), WhatsApp fields used for other purposes (branch contact number, sharing invitation links), patient features.

## Tests
- `backend/tests/test_messaging.py`, `backend/tests/test_procurement.py`.
- `frontend/tests/e2e_messaging_procurement.py`: both dashboards side by side.
