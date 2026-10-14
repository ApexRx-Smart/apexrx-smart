# ApexRX Smart

Website and interactive pharmacy workflow.

## Project structure

- `frontend/index.html`: website home page.
- `frontend/pharmacies.html`: pharmacy registration and demo workspace.
- `frontend/css/`: `style.css` and `pharmacies.css`.
- `frontend/js/`: `script.js`, `pharmacies.js`, `pharmacies-i18n.js`, and `pharmacies-motion.js`.
- `frontend/assets/images/`: audience photos, community image and Kigali map.
- `frontend/assets/logos/`: ApexRX and partner logos.
- `database/`: reserved for database scripts. No SQL file was present in the supplied branch archive; no schema was created or modified. When available, the existing `db_implementation_script.sql` belongs here unchanged.
- `backend/`: reserved for future backend/API implementation. Contains only a Git directory placeholder; no application is implemented.
- `PHARMACY-WORKFLOW.md`: workflow behavior and demo limitations.

## Run locally

From the repository root, with Python 3 installed:

```bash
python3 -m http.server 8000 --directory frontend
```

Open http://localhost:8000/ for the home page, or http://localhost:8000/pharmacies.html for the workflow. Stop the server with Ctrl+C.

For static hosting, set the published directory to `frontend/`. No build step is required. If serving the entire repository root instead, open `/frontend/`.

## Verify after changes

1. Open the home page and check the Kigali map, logos, audience images and animations.
2. Select English, French or Kinyarwanda; open For Pharmacies and confirm the language follows.
3. Follow the demo signup, using a sample email, matching test passwords and verification code `472916`.
4. Continue through profile and simulated payment; check supplier search and demo chat.
5. Check narrow and wide layouts, return navigation and social links.

The workflow remains a frontend demonstration. No real account, document upload, payment or supplier message is submitted. External Google fonts and the existing YouTube background require network access and remain subject to browser/provider restrictions.

## Scope of this reorganization

Only file locations, required relative paths and documentation changed. JavaScript behavior, page content, external/social destinations, visual styles and asset bytes are preserved. The database and backend are kept separate from the frontend.
