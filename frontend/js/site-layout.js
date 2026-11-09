/* ApexRX public site header and footer, shared by index.html, how-it-works.html,
 * about.html and legal.html so the navigation is defined once.
 *
 * Include it where each part belongs; it renders synchronously at that spot,
 * before js/script.js runs (which adds translations, the mobile menu and the
 * Sign in / Get started buttons):
 *   <body data-page="home|how|about|legal">
 *   <script src="js/site-layout.js" data-part="header"></script>
 *   ...page content...
 *   <script src="js/site-layout.js" data-part="footer"></script>
 *
 * Text carries data-i18n keys from js/script.js, so the language switch keeps
 * working on every page.
 */
(function () {
  'use strict';
  var script = document.currentScript;
  if (!script) return;
  var page = document.body.getAttribute('data-page') || 'home';
  var home = page === 'home';
  // On the landing page the search is on this page; elsewhere go there first.
  var searchHref = home ? '#hero-search' : 'index.html#hero-search';
  var brandHref = home ? '#top' : 'index.html';

  function current(name) { return page === name ? ' aria-current="page"' : ''; }

  // "For Patients" is not in the main navigation: patients use the medicine
  // search on the landing page and have no account journey.
  var NAV =
    '<a href="pharmacies.html" data-i18n="nav_pharmacies">For Pharmacies</a>' +
    '<a href="suppliers.html" data-i18n="nav_suppliers">For Suppliers</a>' +
    '<a href="how-it-works.html" data-i18n="nav_how"' + current('how') + '>How it works</a>' +
    '<a href="about.html" data-i18n="nav_about"' + current('about') + '>About</a>';

  var HEADER =
    '<header class="site" id="siteHeader">' +
    '  <div class="header-pill">' +
    '    <a class="brand" href="' + brandHref + '" aria-label="ApexRX_Smart, home">' +
    '      <img class="brand-mark" src="assets/logos/logo-mark.svg" alt="" width="40" height="38">' +
    '      <span class="brand-name">ApexRX_Smart</span>' +
    '    </a>' +
    '    <nav class="main-nav" aria-label="Main">' + NAV + '</nav>' +
    '    <div class="header-actions">' +
    '      <select class="lang-select" id="langSelect" aria-label="Language">' +
    '        <option value="en">EN</option><option value="fr">FR</option><option value="rw">RW</option>' +
    '      </select>' +
    '      <button class="btn-link" id="signInBtn" data-i18n="btn_signin">Sign in</button>' +
    '      <button class="btn btn-pill" id="getStartedBtn" data-i18n="btn_start">Get started</button>' +
    '      <button class="menu-toggle" id="menuToggle" aria-label="Open menu" aria-expanded="false" aria-controls="mobileNav">☰</button>' +
    '    </div>' +
    '  </div>' +
    '  <nav class="mobile-nav" id="mobileNav" aria-label="Mobile">' + NAV +
    '    <div class="mobile-actions">' +
    '      <button class="btn btn-ghost-light" id="signInBtnMobile" data-i18n="btn_signin">Sign in</button>' +
    '      <button class="btn btn-pill" id="getStartedBtnMobile" data-i18n="btn_start">Get started</button>' +
    '    </div>' +
    '  </nav>' +
    '</header>';

  var SOCIAL =
    '<a href="https://www.linkedin.com/company/136934009/" target="_blank" rel="noopener" aria-label="LinkedIn"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5.2 7.6a2.2 2.2 0 1 0 0-4.4 2.2 2.2 0 0 0 0 4.4ZM3.4 9.2H7V21H3.4V9.2Zm5.9 0h3.5v1.6h.1a3.8 3.8 0 0 1 3.4-1.9c3.7 0 4.4 2.4 4.4 5.5V21h-3.6v-5.8c0-1.4 0-3.2-2-3.2s-2.2 1.5-2.2 3.1V21H9.3V9.2Z"/></svg></a>' +
    '<a href="https://x.com/Apexrxsmar1ogc" target="_blank" rel="noopener" aria-label="X"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18.9 2H22l-6.8 7.8L23.2 22H17l-4.9-7.4L5.6 22H2.4l8.2-9.5L2.9 2h6.3l4.5 6.8L18.9 2ZM17.8 20h1.7L8.1 4H6.3l11.5 16Z"/></svg></a>' +
    '<a href="https://studio.youtube.com/channel/UCS3w0RILCJPdfTgQaqm1AwQ/videos/upload?filter=%5B%5D&amp;sort=%7B%22columnType%22%3A%22date%22%2C%22sortOrder%22%3A%22DESCENDING%22%7D" target="_blank" rel="noopener" aria-label="YouTube"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M22 7.1a3 3 0 0 0-2.1-2.2C18 4.4 12 4.4 12 4.4s-6 0-7.9.5A3 3 0 0 0 2 7.1a31 31 0 0 0-.5 4.9 31 31 0 0 0 .5 4.9A3 3 0 0 0 4.1 19c1.9.6 7.9.6 7.9.6s6 0 7.9-.6a3 3 0 0 0 2.1-2.1 31 31 0 0 0 .5-4.9 31 31 0 0 0-.5-4.9ZM9.8 15.4V8.6l5.7 3.4-5.7 3.4Z"/></svg></a>';

  var FOOTER =
    '<footer class="site footer-wide" id="footer">' +
    '  <div class="wrap">' +
    '    <div class="footer-top">' +
    '      <div class="footer-brand">' +
    '        <a class="brand" href="' + brandHref + '" aria-label="ApexRX_Smart, home">' +
    '          <img class="brand-mark" src="assets/logos/logo-mark.svg" alt="" width="58" height="56">' +
    '          <span class="brand-name">ApexRX_Smart</span>' +
    '        </a>' +
    '        <p data-i18n="footer_tag">Healthy Communities. Brighter Tomorrow. Made for a healthier Rwanda.</p>' +
    '        <div class="partners">' +
    '          <div class="partners-label" data-i18n="partners_label">Partnerships</div>' +
    '          <div class="partners-logos">' +
    '            <a class="partner-badge" href="https://aims.ac.rw/" target="_blank" rel="noopener" aria-label="AIMS Rwanda"><img src="assets/logos/partner-aims.png" alt="AIMS Rwanda, African Institute for Mathematical Sciences"></a>' +
    '            <a class="partner-badge" href="https://mastercardfdn.org/en/" target="_blank" rel="noopener" aria-label="Mastercard Foundation"><img src="assets/logos/partner-mastercard.png" alt="Mastercard Foundation"></a>' +
    '          </div>' +
    '        </div>' +
    '      </div>' +
    '      <div class="footer-social" aria-labelledby="footerSocialHeading">' +
    '        <h3 id="footerSocialHeading" data-i18n="f_social">We are social</h3>' +
    '        <div class="social-row">' + SOCIAL + '</div>' +
    '        <a href="https://www.linkedin.com/company/136934009/" target="_blank" rel="noopener" class="footer-social-connect" data-i18n="footer_connect">Connect with us ↗</a>' +
    '      </div>' +
    '      <nav class="footer-navigation" aria-labelledby="footerLinksHeading">' +
    '        <h3 id="footerLinksHeading" data-i18n="f_quicklinks">Quick links</h3>' +
    '        <div class="footer-cols">' +
    '          <div class="footer-col">' +
    '            <h4 data-i18n="f_product">Product</h4>' +
    '            <a href="' + searchHref + '" data-i18n="nav_patients">For Patients</a>' +
    '            <a href="pharmacies.html" data-i18n="nav_pharmacies">For Pharmacies</a>' +
    '            <a href="suppliers.html" data-i18n="nav_suppliers">For Suppliers</a>' +
    '            <a href="how-it-works.html" data-i18n="nav_how">How it works</a>' +
    '          </div>' +
    '          <div class="footer-col">' +
    '            <h4 data-i18n="f_company">Company</h4>' +
    // All Company links lead to the About page until those pages exist.
    '            <a href="about.html" data-i18n="f_about">About</a>' +
    '            <a href="about.html" data-i18n="f_careers">Careers</a>' +
    '            <a href="about.html" data-i18n="f_blog">Blog</a>' +
    '            <a href="about.html" data-i18n="f_contact">Contact</a>' +
    '          </div>' +
    '          <div class="footer-col">' +
    '            <h4 data-i18n="f_legal">Legal</h4>' +
    '            <a href="legal.html#privacy" data-i18n="f_privacy">Privacy</a>' +
    '            <a href="legal.html#terms" data-i18n="f_terms">Terms of Service</a>' +
    '            <a href="legal.html#cookies" data-i18n="f_cookies">Cookie Policy</a>' +
    '          </div>' +
    '        </div>' +
    '      </nav>' +
    '    </div>' +
    '    <div class="footer-bottom">' +
    // Left-aligned on purpose: Netlify's "Powered by Netlify" badge sits in the
    // bottom-right corner and would cover a right-aligned link.
    '      <div class="footer-legal">' +
    '        <span data-i18n="f_rights">© 2026 ApexRX_Smart. All rights reserved.</span>' +
    '        <span class="footer-sep" aria-hidden="true">·</span>' +
    // Navigation only: admin.html requires an ApexRX administrator sign-in, and
    // every /admin API call is checked by the backend.
    '        <a class="footer-admin-link" href="admin.html" rel="nofollow" data-i18n="f_admin">Admin Portal</a>' +
    '      </div>' +
    '    </div>' +
    '  </div>' +
    '</footer>' +
    '<div data-toast id="toast" role="status"></div>';

  var part = script.getAttribute('data-part');
  if (part === 'header') script.insertAdjacentHTML('beforebegin', HEADER);
  else if (part === 'footer') script.insertAdjacentHTML('beforebegin', FOOTER);
})();
