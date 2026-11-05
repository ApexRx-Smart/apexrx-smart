# Plan: update the README to match main

Goal: the docs describe the code that is live on `main` after PRs #15, #17 and #18.

1. Pull `main`, branch `docs/update-readme`.
2. Root README:
   - The frontend is connected to the API, not a demo.
   - Document `js/config.js` and `js/api.js`.
   - Add a deployment section (Neon, Render, Netlify) and test-data notes.
   - Fix the test database name.
   - Mark the legacy endpoint as unused.
   - Refresh the roadmap.
3. PHARMACY-WORKFLOW.md: replace the "front-end prototype" paragraph with what is now live and what is still simulated.
4. `frontend/README.md` is already current. No change.
5. Testing: docs only. Check links and anchors render on GitHub, and that the commands match `backend/requirements.txt` and `app/core/config.py`.
