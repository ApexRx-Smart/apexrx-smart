# ApexRX Smart — Patient workflow (V3)

From `frontend/index.html`, click **For Patients**, the Patients image or **Get started**. You can also open `frontend/patients.html` directly.

**Interactive preview:** account with fictional details and matching test passwords (8+ characters) → enter demo code `472916` (no email) → search a medicine (try `Paracetamol 500mg` or `Amoxicillin 500mg`) → compare sample pharmacies by indicative price, approximate distance or sample stock → choose a pharmacy → choose a sample pickup day/time → confirm the demo disclaimer → review the simulated reservation in the patient space.

**Skip onboarding:** “Preview the patient space” directly opens the dashboard; from there select “Search another medicine”. The dashboard offers a reservation summary, patient preview profile, link to a **neighborhood** on Google Maps (not a fictitious pharmacy), cancel preview, and restart.

**Language:** English, French and Kinyarwanda. Language preference is inherited from the homepage (`apexrx_lang`), preserved in `?lang=...` links and can be changed at any time without losing progress.

**Data:** `frontend/js/patients-demo-data.js` is generated from the existing `frontend/data/demo-pharmacies.json` to work even when HTML is opened as a file without a local HTTP server. Keep those two files synchronized if demo listings change. All listed pharmacies are imaginary, stock values and RWF prices are illustrative, and proximity is calculated from reference points in Kigali rather than the patient's device location.

**Safety / limitations:** frontend-only. Nothing is submitted to the backend, and there is no real account, email/SMS, availability check, payment, reservation, pharmacy conversation or medical advice. No password, name, email, medicine search or reservation is stored in localStorage; only `apexrx_lang` is persisted, as in the homepage. Refresh clears the session. Do not rely on this mockup for medical decisions or visit a pharmacy based on its simulated listings.

**Changes:** new `frontend/patients.html`, `frontend/css/patients.css`, `frontend/js/patients.js`, `frontend/js/patients-i18n.js`, `frontend/js/patients-demo-data.js`; the existing `frontend/index.html` patient links and `frontend/js/script.js` page-language links/Get started are updated. The pharmacy pages, styles, Kigali map and medical finder are otherwise unchanged.

**Run locally (recommended):**

```bash
cd apexrx-smart/frontend
python3 -m http.server 8000
# Then open http://localhost:8000/ and click For Patients.
```

**Before production:** implement authenticated accounts, real verification, consent/privacy controls, the medicine/pharmacy inventory API, real locations, validated stock update times, safe reservation lifecycle, pharmacy-side acceptance, notifications, and cancellation. Nothing in this demo should be described as live inventory or a confirmed booking.
