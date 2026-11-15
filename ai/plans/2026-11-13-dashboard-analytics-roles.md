# Plan: dashboard charts and analytics for owners and managers only

Branch: `feature/dashboard-analytics-role-restriction`, from `main` at 45507ab.

## What existed (inspected first)
- **Roles.** `MembershipRole` defines owner, manager and staff. `deps.MANAGERS` is owner or manager. `get_org_access(roles=…)` returns 403 for members with another role and 404 for non-members. The dashboards read the role from `/auth/me` (`myRole`) and already use `canManage()` for prices, team and documents.
- **Analytics on the dashboards** (`frontend/js/dashboard.js`):
  - Pharmacy overview: the stock health chart.
  - Supplier overview: the order pipeline with the open order value, and the most requested medicines.
  - Both: the Forecasting screen (SVG charts with example data, `dashboard-forecast.js`), its menu entry, the side Premium card and the "Explore Premium" banner.
- **No server-side protection.** No analytics endpoint existed. The browser computed the charts from `/inventory` and `/purchase-orders`, which staff need for their own work. Any role could see every chart.
- **Other branches.** None has role-restricted analytics. `feature/dashboards-and-registration` is the origin of today's dashboards (merged through PR #34) and shows the charts to every role. The other unmerged branches are early landing pages, the schema, Netlify settings and the patient demo, with nothing about dashboard analytics.

## Changes
- **Backend:** new `GET /organizations/{id}/insights?location_id=` (`app/api/insights.py`, `app/schemas/insights.py`).
  - Access: `roles=MANAGERS`. Staff get 403, non-members, platform admins and other organizations' locations get 404, and anonymous callers get 401.
  - Figures: stock health, order pipeline (suppliers never see drafts), open order value, and most requested medicines (the latest 15 orders, as before).
  - Existing routes are unchanged, and there is no migration.
- **Frontend:**
  - `seesInsights()` (owner or manager) gates the overview charts, the Forecasting entry, the side card and the banner. `go('prem')` falls back to the overview for staff.
  - For staff the layout closes up: the shelf-life panel takes the row on the pharmacy dashboard and the right column on the supplier dashboard.
  - The charts now read from the API instead of from client-side order details. The preview gets the same `insights()` computed from its sample data.
  - If the API refuses (the role changed while the page was open), the page reloads once so it shows what the current role allows.
- **Translations:** one new string, in English, French and Kinyarwanda.

## Not changed
Stock, orders, messages and team permissions for staff. The raw stock and order lists remain readable by staff because their workflows need them.

## Tests
- `backend/tests/test_dashboard_insights.py`: the role matrix on both organization types, outsiders, role changes taking effect immediately, and figures checked against real data.
- `frontend/tests/e2e_dashboard_roles.py`: the browser test for owner, manager and staff on both dashboards. It covers bypass attempts, phone width, demotion while the page is open, and staff workflows.
