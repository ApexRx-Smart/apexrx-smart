# ApexRX — Pharmacy workflow

Open index.html, then choose “For Pharmacies”. You can also open pharmacies.html directly. Keep all files and the assets folder together.

Demo journey: sample email + matching passwords (8 characters minimum) → code 472916 → pharmacy profile → simulated 5,000 RWF monthly plan → dashboard. “Preview the workspace” skips onboarding. The workspace includes supplier search, local demo conversations and a profile summary.

This is a front-end prototype. No account is created, verification email sent, document uploaded, payment taken, supplier contacted or map listing published. Passwords are cleared after the first step; no workflow data is written to browser storage. Refreshing the page resets the demo. Uploaded sample files remain local. The map is illustrative; coordinates can be entered manually. Premium is a feature preview.

Before production: connect backend authentication and email verification, secure document storage and license review, a geocoded map, payment-provider integration with server verification, and live suppliers/chat. Confirm subscription terms and prices. The workflow supports English, French and Kinyarwanda. It inherits apexrx_lang from the home page; language query parameters also preserve the choice when local storage is unavailable. A selector changes the workflow language without losing form progress. Browser-native file picker and validation wording follow the browser language.

Files added: pharmacies.html, pharmacies.css, pharmacies.js, pharmacies-i18n.js. The home page pharmacy links now open pharmacies.html. Existing home-page CSS, JavaScript, Kigali map and wave animations are preserved.

Visual update: consistent Inter typography, animated ambient halos and waves, gentle photo movement, step and dashboard transitions. All movement is disabled when the device requests reduced motion.

Latest visual update: larger six-cell verification control (one accessible input supporting paste/autofill), scroll reveal, subtle background parallax and scroll progress. The Kigali map is brighter. The old ambient halos are replaced with the requested YouTube video via a muted looping embed. The video was not downloaded: direct browser media download failed. Playback requires internet, YouTube embedding permission and browser autoplay support; local file previews may be restricted by YouTube. A static pharmacy image remains underneath as a fallback. The background button removes/reloads the player; reduced-motion preference disables automatic loading. No video file is included. New file: pharmacies-motion.js.
