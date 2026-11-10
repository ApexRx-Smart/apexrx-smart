# Plan: pharmacy and supplier dashboards

Branch: `feature/pharmacy-supplier-dashboards`, from `main` at ec15e28 (after PR #33).

## Context

The `feature/dashboards-and-registration` branch (2dd95a9) has the dashboard designs:
- `pharmacy-dashboard.html` and `supplier-dashboard.html`;
- `js/dashboard.js`, `dashboard-data.js`, `dashboard-i18n.js`, `dashboard-forecast.js` and `theme.js`;
- `css/dashboard.css`.

That branch is older than `main`. Its registration (`onboarding.js`) was superseded by `js/registration.js`, and it predates invitations, sessions and the removal of email.

`main` already has:
- an embedded pharmacy workspace in `pharmacies.html` (`pharmacies.js`, `workspace.js`);
- no supplier screens.

The source branch is only read, never modified.

## Approach

1. **Copy the reference dashboard files unchanged.** These are the two pages, the four dashboard scripts, the theme, the CSS and the two `.webp` hero images.
2. **Connect them to `main`.** The data layer (`dashboard-data.js` `live()`) gets these changes:
   - **Organization choice:** use the one chosen for the tab (`apexrx_selected_pharmacy` / `_supplier`, as registration uses), otherwise the one the user owns, manages, or any.
   - **Locations:** load inactive ones too, for branch management.
   - **Batches:** the backend has none. `batches: false` hides or disables the batch screens. The reference's silent fallback (save the quantity and drop the batch) is not used.
   - **Quote requests by staff:** submit returns 403, so the order stays a draft and the screen says it was not sent.
   - **Team:** invitations, as on `main`, replace the reference's add-member-by-email form. Members can be removed. Branches can be edited and deactivated.
3. **Dashboard script (`dashboard.js`):**
   - organization switcher and user/role label;
   - "Not connected yet" states for batches and expiry;
   - invitation-link flow (email is disabled), with role rules that mirror the backend;
   - draft deletion;
   - preview confirmations say nothing was saved;
   - order screens refresh on navigation;
   - the plan card has no price.
4. **Registration hand-off (`registration.js`):** sign-in and "Open your workspace" go to `<role>-dashboard.html`. Suppliers get a dashboard too. **Just exploring?** opens `?preview=1`. `#review` reopens the review. `?signed_out=` explains a sign-out.
5. **Retire the old workspace:** remove `pharmacies.js`, `workspace.js` and the `#dashboard` markup from `pharmacies.html`. Invitation acceptance links to the dashboards.
6. **Translations:** French and Kinyarwanda for the new strings. The Kinyarwanda needs review by a native speaker.

## Session fixes found while testing (`js/api.js`)

Both were hidden while the workspace sat on the same page as sign-in.

- **Signed-in email kept across pages.** A renewed token on a freshly loaded page dropped the stored email, so the public header showed "Signed in as" with no address.
- **"Stay signed in" works.** The inactivity warning was removed on `pointerdown`, before the button's click, so that click had nothing to land on. The session itself was still kept alive.

## Out of scope (unchanged)

- registration steps;
- homepage;
- admin portal;
- email (stays disabled);
- backend and migrations;
- paid services.

## Tests

- **Backend:** pytest and ruff, with no backend changes.
- **New `frontend/tests/e2e_dashboards.py`:**
  - both dashboards, on real local data;
  - role rules, organization switching and the not-connected states;
  - sign-out, guards and mobile layout.
- **`e2e_workspace.py`:** removed. Its checks moved to the new test.
- **Ported to the dashboards:** `e2e_accounts`, `e2e_no_email` and `e2e_registration`.
- **Unchanged:** the other suites.
- Local backend and a throwaway database only; nothing is written to staging.
