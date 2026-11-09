/* legal.html: show one legal page at a time, chosen by the address
 * (legal.html#privacy, #terms, #cookies). Without JavaScript all three are
 * simply shown one after another. */
(function () {
  'use strict';
  var docs = Array.prototype.slice.call(document.querySelectorAll('.legal-doc'));
  var links = Array.prototype.slice.call(document.querySelectorAll('.legal-nav a[data-doc]'));
  if (!docs.length) return;

  function show() {
    var id = location.hash.replace(/^#/, '');
    var doc = docs.filter(function (d) { return d.id === id; })[0] || docs[0];
    docs.forEach(function (d) { d.hidden = d !== doc; });
    links.forEach(function (a) {
      if (a.getAttribute('data-doc') === doc.id) a.setAttribute('aria-current', 'page');
      else a.removeAttribute('aria-current');
    });
    document.title = doc.getAttribute('data-title') + ' — ApexRX Smart';
    var heading = document.getElementById('legal-heading');
    if (heading) heading.textContent = doc.getAttribute('data-title');
  }
  window.addEventListener('hashchange', function () { show(); window.scrollTo(0, 0); });
  show();
})();
