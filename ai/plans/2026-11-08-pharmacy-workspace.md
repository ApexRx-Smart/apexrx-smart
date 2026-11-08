# Plan: pharmacy workspace (branches, employees, inventory, purchase orders)

Branch: `feature/pharmacy-workspace`, from `main` (29ab860). The audit's findings were re-checked; main is unchanged.

1. **Backend, order policy.**
   - Pharmacy-side submit and cancel require an owner or manager role. The check is in `services/orders.authorize` and reflected in `allowed_actions`.
   - Staff keep view and draft prep (create, edit, delete). The supplier side is unchanged.
   - Tests are in `tests/test_order_role_permissions.py`.
2. **Frontend.** Extend the existing workspace (`pharmacies.html` / `pharmacies.js`) and add a new `js/workspace.js` for the sections. Reuse the existing `api.js` wrappers.
   - **Organization selector** for users in several pharmacies. The selection is kept per tab.
   - **Overview:** live organization name, status, active branches, members, recent orders. No invented figures.
   - **Branches:** list (active and inactive), add, edit, deactivate/reactivate. Owners and managers only.
   - **Employees:** list, add an existing account by email with a role, change role, deactivate/reactivate, remove. The backend role rules are mirrored, with errors shown.
   - **Inventory:** branch selector, list, set quantity (all roles), price and listing (owners and managers), add a catalogue product to a branch.
   - **Orders:** list; new order (receiving branch, supplier stock search, items, optional supplier warehouse) saved as a draft; detail with items and history. Action buttons come from the backend's `allowed_actions`, and cancel requires a reason.
   - **Joining an existing pharmacy:** after sign-in with no organization, offer "I'm joining an existing pharmacy" with a "check again" option, instead of forcing pharmacy creation.
3. **Tests.**
   - Backend: the full suite.
   - Browser: `frontend/tests/e2e_workspace.py`, covering all 18 required scenarios against a local backend and throwaway data created through the API.
   - Regression: the existing browser tests.
4. **Restrictions.** No migrations, no seeding of shared environments, no deploy.
