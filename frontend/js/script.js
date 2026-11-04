(function(){
  "use strict";

  /* ================= TRANSLATIONS (EN / FR / RW) ================= */
  var STRINGS = {
    en: {
      stats_eyebrow:'ApexRX in numbers', stats_title:'One city. Better connected.',
      stat_districts:'districts',
      motion_pause:'Pause image motion', motion_resume:'Resume image motion',
      community_tag:'Closer to care.', community_caption:'Connecting people, pharmacies and possibilities.', how_map_label:'One city. A connected medicine network.', footer_invite:'Better access starts with connection.', footer_connect:'Connect with us ↗',
      nav_patients:'For Patients', nav_pharmacies:'For Pharmacies', nav_suppliers:'For Suppliers', nav_how:'How it works', nav_about:'About',
      btn_signin:'Sign in', btn_start:'Get started',
      h1_pre:'Find the medicines you need in ', h1_accent:'Kigali.',
      hero_lede:'Real-time information from pharmacies across Kigali, helping you access the right medicines, faster and easier.',
      hero_search_ph:'Search for a medicine, e.g. Amoxicillin 500mg',
      hero_search_btn:'Search',
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
      how1_h3:'Search', how1_p:'Look for a medicine.',
      how2_h3:'Check availability', how2_p:'See real-time stock at nearby pharmacies.',
      how3_h3:'Get your medicine', how3_p:'Visit the pharmacy or request a supplier.',
      footer_tag:'Healthy Communities. Brighter Tomorrow. Made for a healthier Rwanda.',
      f_social:'We are social', f_quicklinks:'Quick links',
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
      no_result:'No matching medicine found nearby. Try a different name.',
      t_signin:'Sign in is coming soon.', t_start:'Thanks for your interest. Onboarding opens soon.',
      t_results:'Results for',
      t_updated:'Updated', t_searching:'Searching...', t_search_error:'Unable to load medicine availability. Please try again.'
    },
    fr: {
      stats_eyebrow:'ApexRX en chiffres', stats_title:'Une ville. Mieux connectée.',
      stat_districts:'districts',
      motion_pause:'Mettre les images en pause', motion_resume:'Animer les images',
      community_tag:'Plus près des soins.', community_caption:'Relier les habitants, les pharmacies et les possibilités.', how_map_label:'Une ville. Un réseau de pharmacies connecté.', footer_invite:'Un meilleur accès commence par un lien.', footer_connect:'Restons en contact ↗',
      nav_patients:'Patients', nav_pharmacies:'Pharmacies', nav_suppliers:'Fournisseurs', nav_how:'Comment ça marche', nav_about:'À propos',
      btn_signin:'Se connecter', btn_start:'Commencer',
      h1_pre:'Trouvez les médicaments dont vous avez besoin à ', h1_accent:'Kigali.',
      hero_lede:'Des informations en temps réel venant des pharmacies de Kigali, pour accéder plus vite et plus facilement aux bons médicaments.',
      hero_search_ph:'Recherchez un médicament, ex. Amoxicilline 500mg',
      hero_search_btn:'Rechercher',
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
      how1_h3:'Rechercher', how1_p:'Cherchez un médicament.',
      how2_h3:'Vérifier la disponibilité', how2_p:'Consultez le stock en temps réel des pharmacies proches.',
      how3_h3:'Obtenir votre médicament', how3_p:'Rendez-vous en pharmacie ou sollicitez un fournisseur.',
      footer_tag:'Healthy Communities. Brighter Tomorrow. Conçu pour un Rwanda en meilleure santé.',
      f_social:'Suivez-nous', f_quicklinks:'Liens utiles',
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
      no_result:'Aucun médicament correspondant à proximité. Essayez un autre nom.',
      t_signin:'La connexion arrive bientôt.', t_start:'Merci de votre intérêt. L’inscription ouvre bientôt.',
      t_results:'Résultats pour',
      t_updated:'Mis à jour', t_searching:'Recherche...', t_search_error:'Impossible de charger la disponibilité. Veuillez réessayer.'
    },
    /* Kinyarwanda: à faire relire par un locuteur natif avant la mise en ligne */
    rw: {
      stats_eyebrow:'ApexRX mu mibare', stats_title:'Umujyi umwe. Turushaho guhuzwa.',
      stat_districts:'uturere',
      motion_pause:'Hagarika amashusho', motion_resume:'Komeza amashusho',
      community_tag:'Hafi y’ubuvuzi.', community_caption:'Guhuza abantu na farumasi.', how_map_label:'Umujyi umwe. Farumasi zihujwe.', footer_invite:'Guhuzwa bituma kubona imiti byoroha.', footer_connect:'Tuvugishe ↗',
      nav_patients:'Abarwayi', nav_pharmacies:'Farumasi', nav_suppliers:'Abatanga imiti', nav_how:'Uko bikora', nav_about:'Abo turi bo',
      btn_signin:'Injira', btn_start:'Tangira',
      h1_pre:'Shaka imiti ukeneye i ', h1_accent:'Kigali.',
      hero_lede:'Amakuru y’ako kanya aturuka muri farumasi zo muri Kigali, agufasha kubona imiti ikwiye vuba kandi byoroshye.',
      hero_search_ph:'Shakisha umuti, urugero: Amoxicillin 500mg',
      hero_search_btn:'Shakisha',
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
      how1_h3:'Shakisha', how1_p:'Shakisha umuti.',
      how2_h3:'Reba ko uhari', how2_p:'Reba ububiko bwa farumasi ziri hafi ako kanya.',
      how3_h3:'Bona umuti wawe', how3_p:'Jya kuri farumasi cyangwa usabe utanga imiti.',
      footer_tag:'Healthy Communities. Brighter Tomorrow. Twubakira u Rwanda rufite ubuzima bwiza.',
      f_social:'Dukurikire', f_quicklinks:'Aho wahita ujya',
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
      no_result:'Nta muti uhuye n’ibyo washakaga hafi aha. Gerageza irindi zina.',
      t_signin:'Kwinjira biraza vuba.', t_start:'Murakoze. Kwiyandikisha biraza vuba.',
      t_results:'Ibisubizo bya',
      t_updated:'Byavuguruwe', t_searching:'Turashakisha...', t_search_error:'Ntibishobotse kubona amakuru y’imiti. Ongera ugerageze.'
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
  // Sign in and Get started both open the pharmacy/supplier account flow.
  // Entering an existing account's email and password there signs you in.
  function openAccountFlow(hash){ location.href = 'pharmacies.html?lang=' + encodeURIComponent(lang) + hash; }
  ['signInBtn','signInBtnMobile'].forEach(function(id){
    document.getElementById(id).addEventListener('click', function(){ openAccountFlow('#signin'); });
  });
  ['getStartedBtn','getStartedBtnMobile'].forEach(function(id){
    document.getElementById(id).addEventListener('click', function(){ openAccountFlow(''); });
  });

  /* ================= STAT COUNTERS ================= */
  var counters = document.querySelectorAll('.num[data-count]');
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  function counterText(el, value){
    var dec = parseInt(el.getAttribute('data-decimals') || '0', 10);
    return value.toFixed(dec) + (el.getAttribute('data-suffix') || '');
  }
  function runCounter(el){
    if(el.getAttribute('data-count-started') === 'true') return;
    el.setAttribute('data-count-started', 'true');
    var target = parseFloat(el.getAttribute('data-count'));
    var t0 = null;
    function step(ts){
      if(t0 === null) t0 = ts;
      var p = Math.min(Math.max((ts - t0) / 2000, 0), 1);
      var eased = 1 - Math.pow(1 - p, 3);
      el.textContent = counterText(el, p === 1 ? target : target * eased);
      if(p < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }
  if(!reduce && 'IntersectionObserver' in window){
    var counterObserver = new IntersectionObserver(function(entries){
      entries.forEach(function(entry){
        if(entry.isIntersecting && entry.intersectionRatio >= 0.35){
          entry.target.classList.add('stat-visible');
          runCounter(entry.target.querySelector('.num[data-count]'));
          counterObserver.unobserve(entry.target);
        }
      });
    }, {threshold:0.35});
    counters.forEach(function(el){
      // Keep a stable accessible value while the visual number counts up.
      el.setAttribute('aria-label', counterText(el, parseFloat(el.getAttribute('data-count'))));
      el.textContent = counterText(el, 0);
      counterObserver.observe(el.closest('.stat'));
    });
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
    try{ localStorage.setItem('apexrx_lang', lang); }catch(e){}
    document.querySelectorAll('a[href^="pharmacies.html"]').forEach(function(a){ a.href = 'pharmacies.html?lang=' + lang; });
  }
  var langSelect = document.getElementById('langSelect');
  var saved = 'en';
  try{ saved = new URLSearchParams(location.search).get('lang') || localStorage.getItem('apexrx_lang') || 'en'; }catch(e){}
  langSelect.value = STRINGS[saved] ? saved : 'en';
  langSelect.addEventListener('change', function(){ applyLang(langSelect.value); });
  applyLang(langSelect.value);

  /* ================= MEDICINE SEARCH =================
     Public patient search: GET /search/pharmacies?q=...
     Patients see availability status, price, location and freshness only,
     never exact stock quantities. */
  var searchForm = document.getElementById('medicineSearchForm');
  var searchInput = document.getElementById('medicineSearchInput');
  var searchResults = document.getElementById('medicineSearchResults');
  var searchStatus = document.getElementById('medicineSearchStatus');
  var STOCK_CLASS = { in_stock: ['in', 'stock_in'], low_stock: ['low', 'stock_low'], unavailable: ['out', 'stock_out'] };
  var LOCALES = { en: 'en-GB', fr: 'fr-FR', rw: 'rw-RW' };
  var activeSearch = null;

  function formatPrice(amount, currency){
    var n = Number(amount);
    if(!isFinite(n)) return '';
    try{
      return new Intl.NumberFormat(LOCALES[lang] || 'en-GB', {style:'currency', currency:currency || 'RWF', maximumFractionDigits:2}).format(n);
    }catch(e){ return (currency || '') + ' ' + n.toLocaleString(); }
  }
  function formatAge(iso){
    var then = new Date(iso).getTime();
    if(!isFinite(then)) return '';
    var mins = Math.max(0, Math.round((Date.now() - then) / 60000));
    try{
      var rtf = new Intl.RelativeTimeFormat(LOCALES[lang] || 'en-GB', {numeric:'auto'});
      if(mins < 60) return rtf.format(-mins, 'minute');
      if(mins < 1440) return rtf.format(-Math.round(mins / 60), 'hour');
      return rtf.format(-Math.round(mins / 1440), 'day');
    }catch(e){ return new Date(iso).toLocaleDateString(); }
  }
  function textRow(className, text){
    var el = document.createElement('div'); el.className = className; el.textContent = text; return el;
  }
  function medicineLabel(m){
    return [m.product_name || m.drug_name, m.strength, m.dosage_form]
      .filter(function(part, i, all){ return part && (i === 0 || String(all[0]).toLowerCase().indexOf(String(part).toLowerCase()) === -1); })
      .join(' · ') || 'Medicine';
  }

  if (searchForm && searchInput && searchResults && searchStatus && window.ApexAPI) {
    searchForm.addEventListener('submit', function (event) {
      event.preventDefault();
      var query = searchInput.value.trim();
      if (query.length < 2) { searchInput.focus(); return; }

      if (activeSearch) activeSearch.abort();
      var controller = typeof AbortController === 'function' ? new AbortController() : null;
      activeSearch = controller;

      searchStatus.textContent = t('t_searching');
      searchResults.classList.add('open');
      searchResults.replaceChildren();

      ApexAPI.search.pharmacies({ q: query, sort: 'freshness', limit: 20 }, { signal: controller ? controller.signal : undefined })
        .then(function (page) {
          if (activeSearch !== controller) return;
          searchStatus.textContent = '';
          var matches = (page && page.items) || [];

          if (matches.length === 0) {
            searchResults.appendChild(textRow('result-empty', t('no_result')));
            return;
          }
          searchResults.appendChild(textRow('result-empty', t('t_results') + ' "' + query + '"'));

          matches.forEach(function (m) {
            var row = document.createElement('div');
            row.className = 'result-row';
            var details = document.createElement('div');
            var place = m.location_name && m.location_name !== m.pharmacy_name
              ? m.pharmacy_name + ' (' + m.location_name + ')' : m.pharmacy_name;
            var meta = [place, m.address, formatPrice(m.unit_price, m.currency), t('t_updated') + ' ' + formatAge(m.last_updated)]
              .filter(Boolean).join(' · ');
            details.appendChild(textRow('rname', medicineLabel(m)));
            details.appendChild(textRow('rmeta', meta));

            var status = STOCK_CLASS[m.availability_status] || STOCK_CLASS.in_stock;
            var stock = document.createElement('span');
            stock.className = 'rstock ' + status[0];
            stock.textContent = t(status[1]);

            row.appendChild(details);
            row.appendChild(stock);
            searchResults.appendChild(row);
          });
        })
        .catch(function (error) {
          if (controller && controller.signal.aborted && activeSearch !== controller) return;
          console.error('Medicine search failed:', error);
          searchStatus.textContent = (error && error.status === 0) ? error.message : t('t_search_error');
        });
    });
  }
})();
