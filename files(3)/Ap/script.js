(function(){
  "use strict";

  /* ================= TRANSLATIONS (EN / FR / RW) ================= */
  var STRINGS = {
    en: {
      nav_patients:'For Patients', nav_pharmacies:'For Pharmacies', nav_suppliers:'For Suppliers', nav_how:'How it works', nav_about:'About',
      btn_signin:'Sign in', btn_start:'Get started',
      h1_pre:'Find the medicines you need in ', h1_accent:'Kigali.',
      hero_lede:'Real-time information from pharmacies across Kigali, helping you access the right medicines, faster and easier.',
      hero_search_ph:'Search for a medicine, e.g. Amoxicillin 500mg',
      hero_search_btn:'Search', hero_or:'or', hero_upload:'Upload prescription',
      hero_upload_note:'Take a photo or upload a prescription to find available medicines',
      stat1_lbl:'Pharmacies in Kigali', stat1_sub:'and growing',
      stat2_lbl:'Medicines tracked', stat2_sub:'in real time',
      stat3_lbl:'Availability accuracy', stat3_sub:'Trusted data',
      stat4_num:'3 districts', stat4_lbl:'Gasabo · Kicukiro · Nyarugenge', stat4_sub:'All of Kigali connected',
      aud_h2:'Built for everyone in the medicine chain',
      aud_p:'Whoever you are, ApexRX_Smart gives you the information you need to act with confidence.',
      aud1_h3:'For Patients', aud1_p:'Find nearby pharmacies and avoid unnecessary trips.',
      aud2_h3:'For Pharmacies', aud2_p:'Manage inventory and reach more patients.',
      aud3_h3:'For Healthcare Professionals', aud3_p:'Check medicine availability to make informed decisions.',
      aud4_h3:'For Suppliers', aud4_p:'Connect with pharmacies and respond to demand.',
      aud_learn:'Learn more →',
      how_h2:'From search to access, in three simple steps',
      how_p:'Simple and fast, wherever you are in Kigali.',
      how1_h3:'Search', how1_p:'Look for a medicine or upload a prescription.',
      how2_h3:'Check availability', how2_p:'See real-time stock at nearby pharmacies.',
      how3_h3:'Get your medicine', how3_p:'Visit the pharmacy or request a supplier.',
      footer_tag:'Healthy Communities. Brighter Tomorrow. Made for a healthier Rwanda.',
      f_product:'Product', f_company:'Company', f_legal:'Legal',
      f_about:'About', f_careers:'Careers', f_blog:'Blog', f_contact:'Contact',
      f_privacy:'Privacy', f_terms:'Terms of Service', f_cookies:'Cookie Policy',
      f_rights:'© 2026 ApexRX_Smart. All rights reserved.',
      partners_label:'Partnerships',
      hero_live:'Live stock across Kigali', hero_try:'Try:',
      hero_pharm_q:'Own a pharmacy in Kigali?', hero_pharm_cta:'Join ApexRX_Smart',
      aud_eyebrow:'— For everyone in the medicine chain', how_eyebrow:'— How it works',
      cta_h2:'Healthy Communities. Brighter Tomorrow.', cta_p:'Made for a healthier Rwanda.', cta_search:'Find a medicine',
      stock_in:'In stock', stock_low:'Low stock', stock_out:'Out of stock',
      no_result:'No matching medicine found nearby. Try a different name or upload your prescription.',
      t_signin:'Sign in is coming soon.', t_start:'Thanks for your interest. Onboarding opens soon.',
      t_results:'Results for', t_upload:'Prescription received. Matching it against nearby pharmacies.', t_selected:'Selected:'
    },
    fr: {
      nav_patients:'Patients', nav_pharmacies:'Pharmacies', nav_suppliers:'Fournisseurs', nav_how:'Comment ça marche', nav_about:'À propos',
      btn_signin:'Se connecter', btn_start:'Commencer',
      h1_pre:'Trouvez les médicaments dont vous avez besoin à ', h1_accent:'Kigali.',
      hero_lede:'Des informations en temps réel venant des pharmacies de Kigali, pour accéder plus vite et plus facilement aux bons médicaments.',
      hero_search_ph:'Recherchez un médicament, ex. Amoxicilline 500mg',
      hero_search_btn:'Rechercher', hero_or:'ou', hero_upload:'Envoyer une ordonnance',
      hero_upload_note:'Prenez une photo ou envoyez une ordonnance pour trouver les médicaments disponibles',
      stat1_lbl:'Pharmacies à Kigali', stat1_sub:'et ce n’est qu’un début',
      stat2_lbl:'Médicaments suivis', stat2_sub:'en temps réel',
      stat3_lbl:'Précision des stocks', stat3_sub:'Données fiables',
      stat4_num:'3 districts', stat4_lbl:'Gasabo · Kicukiro · Nyarugenge', stat4_sub:'Tout Kigali connecté',
      aud_h2:'Pensé pour chaque acteur de la chaîne du médicament',
      aud_p:'Quel que soit votre rôle, ApexRX_Smart vous donne les informations nécessaires pour agir en confiance.',
      aud1_h3:'Pour les patients', aud1_p:'Trouvez les pharmacies proches et évitez les déplacements inutiles.',
      aud2_h3:'Pour les pharmacies', aud2_p:'Gérez votre stock et touchez davantage de patients.',
      aud3_h3:'Pour les professionnels de santé', aud3_p:'Vérifiez la disponibilité des médicaments pour décider en connaissance de cause.',
      aud4_h3:'Pour les fournisseurs', aud4_p:'Connectez-vous aux pharmacies et répondez à la demande.',
      aud_learn:'En savoir plus →',
      how_h2:'De la recherche au médicament, en trois étapes',
      how_p:'Simple et rapide, où que vous soyez à Kigali.',
      how1_h3:'Rechercher', how1_p:'Cherchez un médicament ou envoyez une ordonnance.',
      how2_h3:'Vérifier la disponibilité', how2_p:'Consultez le stock en temps réel des pharmacies proches.',
      how3_h3:'Obtenir votre médicament', how3_p:'Rendez-vous en pharmacie ou sollicitez un fournisseur.',
      footer_tag:'Healthy Communities. Brighter Tomorrow. Conçu pour un Rwanda en meilleure santé.',
      f_product:'Produit', f_company:'Entreprise', f_legal:'Mentions légales',
      f_about:'À propos', f_careers:'Carrières', f_blog:'Blog', f_contact:'Contact',
      f_privacy:'Confidentialité', f_terms:'Conditions d’utilisation', f_cookies:'Cookies',
      f_rights:'© 2026 ApexRX_Smart. Tous droits réservés.',
      partners_label:'Partenaires',
      hero_live:'Stocks en direct à Kigali', hero_try:'Essayez :',
      hero_pharm_q:'Vous avez une pharmacie à Kigali ?', hero_pharm_cta:'Rejoindre ApexRX_Smart',
      aud_eyebrow:'— Pour toute la chaîne du médicament', how_eyebrow:'— Comment ça marche',
      cta_h2:'Healthy Communities. Brighter Tomorrow.', cta_p:'Conçu pour un Rwanda en meilleure santé.', cta_search:'Trouver un médicament',
      stock_in:'En stock', stock_low:'Stock faible', stock_out:'Rupture',
      no_result:'Aucun médicament correspondant à proximité. Essayez un autre nom ou envoyez votre ordonnance.',
      t_signin:'La connexion arrive bientôt.', t_start:'Merci de votre intérêt. L’inscription ouvre bientôt.',
      t_results:'Résultats pour', t_upload:'Ordonnance reçue. Recherche dans les pharmacies proches.', t_selected:'Fichier :'
    },
    /* Kinyarwanda: à faire relire par un locuteur natif avant la mise en ligne */
    rw: {
      nav_patients:'Abarwayi', nav_pharmacies:'Farumasi', nav_suppliers:'Abatanga imiti', nav_how:'Uko bikora', nav_about:'Abo turi bo',
      btn_signin:'Injira', btn_start:'Tangira',
      h1_pre:'Shaka imiti ukeneye i ', h1_accent:'Kigali.',
      hero_lede:'Amakuru y’ako kanya aturuka muri farumasi zo muri Kigali, agufasha kubona imiti ikwiye vuba kandi byoroshye.',
      hero_search_ph:'Shakisha umuti, urugero: Amoxicillin 500mg',
      hero_search_btn:'Shakisha', hero_or:'cyangwa', hero_upload:'Ohereza urupapuro rwa muganga',
      hero_upload_note:'Fata ifoto cyangwa wohereze urupapuro rwa muganga kugira ngo ubone imiti iboneka',
      stat1_lbl:'Farumasi muri Kigali', stat1_sub:'kandi ziriyongera',
      stat2_lbl:'Imiti ikurikiranwa', stat2_sub:'ako kanya',
      stat3_lbl:'Ukuri kw’amakuru', stat3_sub:'Amakuru yizewe',
      stat4_num:'Uturere 3', stat4_lbl:'Gasabo · Kicukiro · Nyarugenge', stat4_sub:'Kigali yose ihujwe',
      aud_h2:'Byakorewe buri wese mu ruhererekane rw’imiti',
      aud_p:'Uwo uri we wese, ApexRX_Smart iguha amakuru ukeneye kugira ngo ufate icyemezo wizeye.',
      aud1_h3:'Ku barwayi', aud1_p:'Shaka farumasi ziri hafi yawe kandi wirinde ingendo zidakenewe.',
      aud2_h3:'Ku bafarumasiye', aud2_p:'Genzura ububiko bwawe kandi ugere ku barwayi benshi.',
      aud3_h3:'Ku bakora mu buvuzi', aud3_p:'Reba imiti iboneka kugira ngo ufate ibyemezo bikwiye.',
      aud4_h3:'Ku batanga imiti', aud4_p:'Korana na farumasi kandi usubize ibikenewe.',
      aud_learn:'Menya byinshi →',
      how_h2:'Kuva ku gushakisha kugeza ku kubona umuti, mu ntambwe eshatu',
      how_p:'Byoroshye kandi byihuse, aho uri hose muri Kigali.',
      how1_h3:'Shakisha', how1_p:'Shakisha umuti cyangwa wohereze urupapuro rwa muganga.',
      how2_h3:'Reba ko uhari', how2_p:'Reba ububiko bwa farumasi ziri hafi ako kanya.',
      how3_h3:'Bona umuti wawe', how3_p:'Jya kuri farumasi cyangwa usabe utanga imiti.',
      footer_tag:'Healthy Communities. Brighter Tomorrow. Twubakira u Rwanda rufite ubuzima bwiza.',
      f_product:'Serivisi', f_company:'Ikigo', f_legal:'Amategeko',
      f_about:'Abo turi bo', f_careers:'Akazi', f_blog:'Inkuru', f_contact:'Twandikire',
      f_privacy:'Ibanga', f_terms:'Amabwiriza', f_cookies:'Cookies',
      f_rights:'© 2026 ApexRX_Smart. Uburenganzira bwose burasigasiwe.',
      partners_label:'Abafatanyabikorwa',
      hero_live:'Ububiko bw’ako kanya muri Kigali', hero_try:'Gerageza:',
      hero_pharm_q:'Ufite farumasi muri Kigali?', hero_pharm_cta:'Injira muri ApexRX_Smart',
      aud_eyebrow:'— Kuri buri wese mu ruhererekane rw’imiti', how_eyebrow:'— Uko bikora',
      cta_h2:'Healthy Communities. Brighter Tomorrow.', cta_p:'Twubakira u Rwanda rufite ubuzima bwiza.', cta_search:'Shaka umuti',
      stock_in:'Irahari', stock_low:'Hasigaye bike', stock_out:'Yashize',
      no_result:'Nta muti uhuye n’ibyo washakaga hafi aha. Gerageza irindi zina cyangwa wohereze urupapuro rwa muganga.',
      t_signin:'Kwinjira biraza vuba.', t_start:'Murakoze. Kwiyandikisha biraza vuba.',
      t_results:'Ibisubizo bya', t_upload:'Urupapuro rwakiriwe. Turashakisha muri farumasi ziri hafi.', t_selected:'Dosiye:'
    }
  };
  var lang = 'en';
  function t(key){ return (STRINGS[lang] && STRINGS[lang][key]) || STRINGS.en[key] || key; }

  /* ================= MOBILE MENU ================= */
  var menuToggle = document.getElementById('menuToggle');
  var mobileNav = document.getElementById('mobileNav');
  function setMenu(open){
    mobileNav.classList.toggle('open', open);
    menuToggle.setAttribute('aria-expanded', open);
    menuToggle.textContent = open ? '✕' : '☰';
  }
  menuToggle.addEventListener('click', function(){ setMenu(!mobileNav.classList.contains('open')); });
  mobileNav.querySelectorAll('a').forEach(function(a){ a.addEventListener('click', function(){ setMenu(false); }); });

  /* ================= TOAST ================= */
  var toastEl = document.getElementById('toast'), toastTimer;
  function toast(msg){
    toastEl.textContent = msg; toastEl.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function(){ toastEl.classList.remove('show'); }, 2600);
  }
  ['signInBtn','signInBtnMobile'].forEach(function(id){
    document.getElementById(id).addEventListener('click', function(){ toast(t('t_signin')); });
  });
  ['getStartedBtn','getStartedBtnMobile'].forEach(function(id){
    document.getElementById(id).addEventListener('click', function(){ toast(t('t_start')); });
  });

  /* ================= MEDICINE SEARCH (demo data) ================= */
  var MEDS = [
    {name:'Amoxicillin 500mg', pharmacy:'Pharmacie La Santé', area:'Nyarugenge', stock:'in'},
    {name:'Amoxicillin 250mg', pharmacy:'Kacyiru Central', area:'Gasabo', stock:'in'},
    {name:'Metformin 500mg', pharmacy:'Nyabugogo Pharmacy', area:'Nyarugenge', stock:'in'},
    {name:'Paracetamol 500mg', pharmacy:'Good Health Pharmacy', area:'Kicukiro', stock:'low'},
    {name:'Paracetamol 500mg', pharmacy:'Rebero Pharmacy', area:'Kicukiro', stock:'in'},
    {name:'Ibuprofen 400mg', pharmacy:'Gasabo Health Point', area:'Gasabo', stock:'in'},
    {name:'Insulin (Rapid)', pharmacy:'Downtown Pharmacy', area:'Nyarugenge', stock:'low'},
    {name:'Amlodipine 5mg', pharmacy:'Kacyiru Central', area:'Gasabo', stock:'in'},
    {name:'Azithromycin 250mg', pharmacy:'Nyamirambo Pharmacy', area:'Nyarugenge', stock:'in'},
    {name:'Salbutamol Inhaler', pharmacy:'Nyarugenge Pharmacy', area:'Nyarugenge', stock:'in'},
    {name:'Vitamin D3', pharmacy:'Kicukiro Family Pharmacy', area:'Kicukiro', stock:'in'},
    {name:'Cetirizine 10mg', pharmacy:'Rebero Pharmacy', area:'Kicukiro', stock:'in'},
    {name:'ORS Sachets', pharmacy:'Airport Rd Pharmacy', area:'Kicukiro', stock:'out'}
  ];
  var searchInput = document.getElementById('medSearch');
  var resultsBox = document.getElementById('searchResults');

  function esc(s){ return String(s).replace(/[&<>"]/g, function(c){ return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); }

  function renderResults(query){
    var q = query.trim().toLowerCase();
    if(!q){ resultsBox.classList.remove('open'); resultsBox.innerHTML=''; return; }
    var matches = MEDS.filter(function(m){ return m.name.toLowerCase().indexOf(q) !== -1; });
    if(matches.length === 0){
      resultsBox.innerHTML = '<div class="result-empty">'+ esc(t('no_result')) +'</div>';
    } else {
      resultsBox.innerHTML = matches.slice(0,6).map(function(m){
        return '<div class="result-row"><div><div class="rname">'+ esc(m.name) +'</div><div class="rmeta">'+ esc(m.pharmacy) +' · '+ esc(m.area) +'</div></div>'+
               '<span class="rstock '+ m.stock +'">'+ esc(t('stock_'+m.stock)) +'</span></div>';
      }).join('');
    }
    resultsBox.classList.add('open');
  }
  searchInput.addEventListener('input', function(){ renderResults(searchInput.value); });
  document.getElementById('searchBtn').addEventListener('click', function(){
    renderResults(searchInput.value);
    if(searchInput.value.trim()) toast(t('t_results') + ' « ' + searchInput.value.trim() + ' »');
  });
  searchInput.addEventListener('keydown', function(e){
    if(e.key === 'Enter'){ e.preventDefault(); document.getElementById('searchBtn').click(); }
  });

  /* ================= UPLOAD PRESCRIPTION (demo) ================= */
  var fileInput = document.getElementById('fileInput');
  var uploadFilename = document.getElementById('uploadFilename');
  document.getElementById('uploadBtn').addEventListener('click', function(){ fileInput.click(); });
  fileInput.addEventListener('change', function(){
    if(fileInput.files && fileInput.files[0]){
      uploadFilename.textContent = t('t_selected') + ' ' + fileInput.files[0].name;
      uploadFilename.classList.add('show');
      toast(t('t_upload'));
    }
  });

  /* ================= STAT COUNTERS ================= */
  var counters = document.querySelectorAll('.num[data-count]');
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  function runCounters(){
    counters.forEach(function(el){
      var target = parseFloat(el.getAttribute('data-count'));
      var dec = parseInt(el.getAttribute('data-decimals') || '0', 10);
      var suffix = el.getAttribute('data-suffix') || '';
      var t0 = null;
      function step(ts){
        if(!t0) t0 = ts;
        var p = Math.min((ts - t0) / 1100, 1), e = 1 - Math.pow(1 - p, 3);
        el.textContent = (target * e).toFixed(dec) + suffix;
        if(p < 1) requestAnimationFrame(step);
      }
      requestAnimationFrame(step);
    });
  }
  if(!reduce && 'IntersectionObserver' in window){
    var io = new IntersectionObserver(function(entries){
      if(entries.some(function(en){ return en.isIntersecting; })){ runCounters(); io.disconnect(); }
    }, {threshold:0.4});
    io.observe(document.querySelector('.stats'));
  }

  /* ================= HEADER / REVEAL / CHIPS ================= */
  document.documentElement.classList.add('js');
  var header = document.getElementById('siteHeader');
  function onScroll(){ header.classList.toggle('scrolled', window.scrollY > 40); }
  window.addEventListener('scroll', onScroll, {passive:true}); onScroll();

  var reveals = document.querySelectorAll('.reveal');
  if('IntersectionObserver' in window && !reduce){
    var rio = new IntersectionObserver(function(entries){
      entries.forEach(function(en){
        if(en.isIntersecting){
          var el = en.target, sib = Array.prototype.indexOf.call(el.parentNode.children, el);
          el.style.transitionDelay = Math.min(sib, 4) * 70 + 'ms';
          el.classList.add('in'); rio.unobserve(el);
        }
      });
    }, {threshold:0.12, rootMargin:'0px 0px -40px 0px'});
    reveals.forEach(function(el){ rio.observe(el); });
  } else { reveals.forEach(function(el){ el.classList.add('in'); }); }

  document.querySelectorAll('.chip').forEach(function(c){
    c.addEventListener('click', function(){ searchInput.value = c.getAttribute('data-q'); renderResults(searchInput.value); searchInput.focus(); });
  });

  /* ================= ANIMATED KIGALI MAP =================
     Pins sit on the pharmacy icons drawn in the map image.
     The image uses object-fit:cover + object-position:center 38%,
     so we reproduce that math to keep pins aligned at every width.
     A canvas draws the live network: arcs between pharmacies with
     "stock updates" travelling along them in the Rwanda colours. */
  var IMG_W = 1672, IMG_H = 941, POS_Y = 0.38;
  var layer = document.getElementById('mapLayer');
  var fx = document.getElementById('mapFx'), ctx = fx.getContext('2d');
  var heroInner = document.querySelector('.hero-inner');
  var pins = Array.prototype.slice.call(document.querySelectorAll('.pin'));
  var nodes = [], edges = [], particles = [], ripples = [], W = 0, H = 0, DPR = 1;
  var COLORS = ['0,161,222', '250,210,1', '58,208,127'];

  pins.forEach(function(pin){
    var st = pin.querySelector('.stock');
    st.setAttribute('data-name', st.textContent);
    pin.addEventListener('click', function(){
      var was = pin.classList.contains('show-card');
      pins.forEach(function(p){ p.classList.remove('show-card'); });
      if(!was){ pin.classList.add('show-card'); ripple(pins.indexOf(pin)); }
      pauseCycle();
    });
    pin.addEventListener('mouseenter', pauseCycle);
  });

  function layout(){
    W = layer.clientWidth; H = layer.clientHeight; DPR = Math.min(window.devicePixelRatio || 1, 2);
    fx.width = W * DPR; fx.height = H * DPR; ctx.setTransform(DPR,0,0,DPR,0,0);
    var s = Math.max(W / IMG_W, H / IMG_H);
    var ox = (W - IMG_W * s) / 2, oy = (H - IMG_H * s) * POS_Y;
    nodes = pins.map(function(pin){
      var x = ox + parseFloat(pin.getAttribute('data-x')) * s;
      var y = oy + parseFloat(pin.getAttribute('data-y')) * s;
      pin.style.left = x + 'px'; pin.style.top = y + 'px';
      pin.hidden = (x < 10 || x > W - 10 || y < 10 || y > H - 10);
      return {x:x, y:y};
    });
    // each pharmacy links to its 2 nearest neighbours
    var seen = {}; edges = [];
    nodes.forEach(function(a, i){
      nodes.map(function(b, j){ return {j:j, d:(a.x-b.x)*(a.x-b.x)+(a.y-b.y)*(a.y-b.y)}; })
        .filter(function(o){ return o.j !== i; })
        .sort(function(p, q){ return p.d - q.d; }).slice(0, 2)
        .forEach(function(o){
          var k = Math.min(i, o.j) + '-' + Math.max(i, o.j);
          if(seen[k]) return; seen[k] = 1;
          var b = nodes[o.j], mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
          var dx = b.x - a.x, dy = b.y - a.y, bend = 0.18;
          edges.push({a:i, b:o.j, cx:mx - dy * bend, cy:my + dx * bend});
        });
    });
    if(reduce) draw(0);
  }
  function qpt(e, t){
    var a = nodes[e.a], b = nodes[e.b], u = 1 - t;
    return {x:u*u*a.x + 2*u*t*e.cx + t*t*b.x, y:u*u*a.y + 2*u*t*e.cy + t*t*b.y};
  }
  function spawn(){
    if(!edges.length) return;
    var e = edges[Math.floor(Math.random() * edges.length)];
    particles.push({e:e, t:0, dir:Math.random() < .5 ? 1 : -1, v:0.0035 + Math.random() * 0.004, c:COLORS[Math.floor(Math.random() * 3)]});
  }
  function ripple(i){ if(nodes[i]) ripples.push({x:nodes[i].x, y:nodes[i].y, r:0, a:.9}); }

  var last = 0, spawnAcc = 0;
  function draw(ts){
    var dt = Math.min(ts - last, 50) || 16; last = ts;
    ctx.clearRect(0, 0, W, H);
    // network arcs
    ctx.lineWidth = 1.2; ctx.setLineDash([4, 6]);
    ctx.strokeStyle = 'rgba(160,230,200,.28)';
    edges.forEach(function(e){
      var a = nodes[e.a], b = nodes[e.b];
      ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.quadraticCurveTo(e.cx, e.cy, b.x, b.y); ctx.stroke();
    });
    ctx.setLineDash([]);
    if(reduce) return;
    // travelling stock updates
    spawnAcc += dt;
    if(spawnAcc > 260 && particles.length < 26){ spawn(); spawnAcc = 0; }
    particles = particles.filter(function(p){
      p.t += p.v * dt / 16;
      if(p.t >= 1){ ripple(p.dir > 0 ? p.e.b : p.e.a); return false; }
      var tt = p.dir > 0 ? p.t : 1 - p.t;
      for(var k = 0; k < 7; k++){               // glowing tail
        var q = qpt(p.e, Math.max(0, Math.min(1, tt - p.dir * k * 0.018)));
        ctx.fillStyle = 'rgba(' + p.c + ',' + (0.9 - k * 0.12) + ')';
        ctx.beginPath(); ctx.arc(q.x, q.y, Math.max(0.6, 3 - k * 0.35), 0, 6.283); ctx.fill();
      }
      var h = qpt(p.e, tt);
      var g = ctx.createRadialGradient(h.x, h.y, 0, h.x, h.y, 12);
      g.addColorStop(0, 'rgba(' + p.c + ',.55)'); g.addColorStop(1, 'rgba(' + p.c + ',0)');
      ctx.fillStyle = g; ctx.beginPath(); ctx.arc(h.x, h.y, 12, 0, 6.283); ctx.fill();
      return true;
    });
    // arrival ripples
    ripples = ripples.filter(function(r){
      r.r += 0.9 * dt / 16; r.a -= 0.018 * dt / 16;
      if(r.a <= 0) return false;
      ctx.strokeStyle = 'rgba(58,208,127,' + r.a + ')'; ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.arc(r.x, r.y, 14 + r.r, 0, 6.283); ctx.stroke();
      return true;
    });
    raf = requestAnimationFrame(draw);
  }
  var raf = null;
  function start(){ if(!raf && !reduce) raf = requestAnimationFrame(draw); }
  function stop(){ if(raf){ cancelAnimationFrame(raf); raf = null; } }

  // only animate while the hero is on screen
  if('IntersectionObserver' in window){
    new IntersectionObserver(function(en){ en[0].isIntersecting ? start() : stop(); }).observe(document.querySelector('.hero'));
  } else start();
  document.addEventListener('visibilitychange', function(){ document.hidden ? stop() : start(); });

  // cycle the "live stock" cards on pharmacies that are not under the headline
  var cycleIdx = -1, cycleTimer = null, pausedUntil = 0;
  function freePins(){
    var box = heroInner.getBoundingClientRect(), pad = 30;
    return pins.filter(function(pin){
      if(pin.hidden || pin.offsetParent === null) return false;
      var r = pin.getBoundingClientRect(), cx = r.left + r.width / 2, cy = r.top + r.height / 2;
      return !(cx > box.left - pad && cx < box.right + pad && cy > box.top - 90 && cy < box.bottom + pad);
    });
  }
  function nextCard(){
    if(Date.now() < pausedUntil) return;
    var free = freePins(); if(!free.length) return;
    cycleIdx = (cycleIdx + 1) % free.length;
    pins.forEach(function(p){ p.classList.remove('show-card'); });
    free[cycleIdx].classList.add('show-card');
    ripple(pins.indexOf(free[cycleIdx]));
  }
  function pauseCycle(){ pausedUntil = Date.now() + 6000; }
  function startCycle(){ if(!cycleTimer){ nextCard(); cycleTimer = setInterval(nextCard, 3200); } }

  function labelPins(){
    pins.forEach(function(pin){
      var st = pin.querySelector('.stock');
      var key = st.classList.contains('low') ? 'stock_low' : (st.classList.contains('out') ? 'stock_out' : 'stock_in');
      st.textContent = st.getAttribute('data-name') + ' · ' + t(key);
      pin.setAttribute('aria-label', st.textContent + ', ' + pin.querySelector('.med').textContent);
    });
  }
  layout();
  var rt; window.addEventListener('resize', function(){ clearTimeout(rt); rt = setTimeout(layout, 120); });
  var bg = layer.querySelector('.map-bg-img');
  if(bg && !bg.complete) bg.addEventListener('load', layout);
  setTimeout(startCycle, 900);

  /* ================= LANGUAGE ================= */
  var h1Pre = document.getElementById('h1Pre'), h1Accent = document.getElementById('h1Accent');
  function applyLang(l){
    lang = STRINGS[l] ? l : 'en';
    h1Pre.textContent = t('h1_pre'); h1Accent.textContent = t('h1_accent');
    document.querySelectorAll('[data-i18n]').forEach(function(el){ el.textContent = t(el.getAttribute('data-i18n')); });
    document.querySelectorAll('[data-i18n-placeholder]').forEach(function(el){ el.setAttribute('placeholder', t(el.getAttribute('data-i18n-placeholder'))); });
    document.documentElement.lang = lang === 'rw' ? 'rw' : lang;
    labelPins();
    renderResults(searchInput.value);
    try{ localStorage.setItem('apexrx_lang', lang); }catch(e){}
  }
  var langSelect = document.getElementById('langSelect');
  var saved = 'en';
  try{ saved = localStorage.getItem('apexrx_lang') || 'en'; }catch(e){}
  langSelect.value = STRINGS[saved] ? saved : 'en';
  langSelect.addEventListener('change', function(){ applyLang(langSelect.value); });
  applyLang(langSelect.value);
})();
