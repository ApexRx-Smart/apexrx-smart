# ApexRX — Pharmacy workflow

Open frontend/index.html, then choose “For Pharmacies”. You can also open frontend/pharmacies.html directly. Keep all files and the assets folder together.

Journey: email + matching passwords (8 characters minimum) → email verified by an emailed link (in development, open the link from `GET /dev/email/latest`) → pharmacy details with a structured Rwandan address → licensing documents → registration review → workspace. There is no plan or payment step. “Preview the workspace” skips onboarding. Suppliers follow the same steps on suppliers.html (js/registration.js serves both). The workspace includes supplier search, local demo conversations and a profile summary.

The workflow is connected to the backend API (see [frontend/README.md](frontend/README.md) for the endpoint of each step):

- **Account:** creates a real account, or signs in if the email is already registered.
- **Verify email:** the backend refuses to register an organization until the account's email is verified.
- **Details and documents:** create the pharmacy organization and its main branch (province, district, sector, cell, village, street, optional coordinates), and upload the verification documents for ApexRX to review.
- **Review:** the real status, ApexRX's note after a rejection, resubmission, and more uploads. Signing in again resumes an incomplete registration.
- **Workspace:** shows the live profile and document review status, suppliers from the pharmacy's purchase orders, and supplier stock search. Search works only once ApexRX has approved the pharmacy.
- **Supplier contact:** **Open chat** opens the supplier's WhatsApp or phone.

The access token is kept in `sessionStorage`, so a refresh resumes the session and closing the tab signs out. Passwords are never stored in the browser. **Restart demo** signs out. "Preview the workspace" and "Just exploring?" still show sample data without an account.

Still simulated: in-app chat messages, which stay in the browser. Coordinates come from the device's location or are entered manually, with a link to check them on OpenStreetMap. Premium is a feature preview.

Before production: configure a real email provider and domain (see the root README, "Email verification"), check the list of Rwandan places against official data, and have the Kinyarwanda strings reviewed. Subscriptions and payments are not part of registration. The workflow supports English, French and Kinyarwanda. It inherits apexrx_lang from the home page; language query parameters also preserve the choice when local storage is unavailable. A selector changes the workflow language without losing form progress. Browser-native file picker and validation wording follow the browser language.

Files added: pharmacies.html, pharmacies.css, pharmacies.js, pharmacies-i18n.js. The home page pharmacy links now open pharmacies.html. Existing home-page CSS, JavaScript, Kigali map and wave animations are preserved.

Visual update: consistent Inter typography, animated ambient halos and waves, gentle photo movement, step and dashboard transitions. All movement is disabled when the device requests reduced motion.

Latest visual update: larger six-cell verification control (one accessible input supporting paste/autofill), scroll reveal, subtle background parallax and scroll progress. The Kigali map is brighter. The old ambient halos are replaced with the requested YouTube video via a muted looping embed. The video was not downloaded: direct browser media download failed. Playback requires internet, YouTube embedding permission and browser autoplay support; local file previews may be restricted by YouTube. A static pharmacy image remains underneath as a fallback. The background button removes/reloads the player; reduced-motion preference disables automatic loading. No video file is included. New file: pharmacies-motion.js.

## File organization

HTML pages are in `frontend/`; stylesheets in `frontend/css/`; scripts in `frontend/js/`; photos and maps in `frontend/assets/images/`; logos in `frontend/assets/logos/`. HTML asset paths are relative to the page, while CSS image URLs start with `../assets/`. See the root README for local serving instructions.
