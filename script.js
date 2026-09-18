(function(){
  "use strict";

  /* ---- Mobile menu ---- */
  var menuToggle = document.getElementById('menuToggle');
  var mobileNav = document.getElementById('mobileNav');
  menuToggle.addEventListener('click', function(){
    var open = mobileNav.classList.toggle('open');
    menuToggle.setAttribute('aria-expanded', open);
    menuToggle.textContent = open ? '✕' : '☰';
  });
  mobileNav.querySelectorAll('a').forEach(function(a){
    a.addEventListener('click', function(){ mobileNav.classList.remove('open'); menuToggle.textContent='☰'; });
  });

  /* ---- Toast helper ---- */
  var toastEl = document.getElementById('toast');
  var toastTimer;
  function toast(msg){
    toastEl.textContent = msg;
    toastEl.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function(){ toastEl.classList.remove('show'); }, 2600);
  }
  document.getElementById('signInBtn').addEventListener('click', function(){ toast('Sign in — coming soon'); });
  document.getElementById('getStartedBtn').addEventListener('click', function(){ toast('Thanks for your interest — onboarding coming soon'); });

  /* ---- Medicine search (client-side demo dataset) ---- */
  var MEDS = [
    {name:'Amoxicillin 500mg', pharmacy:'Pharmacie La Santé', area:'Gasabo', stock:'in'},
    {name:'Amoxicillin 250mg', pharmacy:'Kiccyiru Central', area:'Kiccyiru', stock:'in'},
    {name:'Metformin 500mg', pharmacy:'Nyabugogo Pharmacy', area:'Nyabugogo', stock:'in'},
    {name:'Paracetamol 500mg', pharmacy:'Good Health Pharmacy', area:'Kicukiro', stock:'low'},
    {name:'Paracetamol 500mg', pharmacy:'Rebero Pharmacy', area:'Rebero', stock:'in'},
    {name:'Ibuprofen 400mg', pharmacy:'Gasabo Health Point', area:'Gasabo', stock:'in'},
    {name:'Insulin (Rapid)', pharmacy:'Downtown Pharmacy', area:'Nyarugenge', stock:'low'},
    {name:'Amlodipine 5mg', pharmacy:'Kiccyiru Central', area:'Kiccyiru', stock:'in'},
    {name:'Azithromycin 250mg', pharmacy:'Kimironko Pharmacy', area:'Kimironko', stock:'in'},
    {name:'Salbutamol Inhaler', pharmacy:'Nyarugenge Pharmacy', area:'Nyarugenge', stock:'in'},
    {name:'Vitamin D3', pharmacy:'Kicukiro Family Pharmacy', area:'Kicukiro', stock:'in'},
    {name:'Cetirizine 10mg', pharmacy:'Rebero Pharmacy', area:'Rebero', stock:'in'},
    {name:'ORS Sachets', pharmacy:'Airport Rd Pharmacy', area:'Airport Rd', stock:'out'}
  ];
  var stockLabel = {in:'In stock', low:'Low stock', out:'Out of stock'};

  var searchInput = document.getElementById('medSearch');
  var resultsBox = document.getElementById('searchResults');

  function renderResults(query){
    var q = query.trim().toLowerCase();
    if(!q){ resultsBox.classList.remove('open'); resultsBox.innerHTML=''; return; }
    var matches = MEDS.filter(function(m){ return m.name.toLowerCase().indexOf(q) !== -1; });
    resultsBox.innerHTML = '';
    if(matches.length === 0){
      resultsBox.innerHTML = '<div class="result-empty">No matching medicine found nearby. Try a different name or upload your prescription instead.</div>';
    } else {
      matches.slice(0,6).forEach(function(m){
        var row = document.createElement('div');
        row.className = 'result-row';
        row.innerHTML =
          '<div><div class="rname">'+ m.name +'</div><div class="rmeta">'+ m.pharmacy +' · '+ m.area +'</div></div>' +
          '<span class="rstock '+ m.stock +'">'+ stockLabel[m.stock] +'</span>';
        resultsBox.appendChild(row);
      });
    }
    resultsBox.classList.add('open');
  }

  searchInput.addEventListener('input', function(){ renderResults(searchInput.value); });
  document.getElementById('searchBtn').addEventListener('click', function(){
    renderResults(searchInput.value);
    if(searchInput.value.trim()) toast('Showing results for "'+ searchInput.value.trim() +'"');
  });
  searchInput.addEventListener('keydown', function(e){
    if(e.key === 'Enter'){ e.preventDefault(); document.getElementById('searchBtn').click(); }
  });

  /* ---- Upload prescription (demo) ---- */
  var uploadBtn = document.getElementById('uploadBtn');
  var fileInput = document.getElementById('fileInput');
  var uploadFilename = document.getElementById('uploadFilename');
  uploadBtn.addEventListener('click', function(){ fileInput.click(); });
  fileInput.addEventListener('change', function(){
    if(fileInput.files && fileInput.files[0]){
      uploadFilename.textContent = 'Selected: ' + fileInput.files[0].name;
      uploadFilename.classList.add('show');
      toast('Prescription received — matching against nearby pharmacies');
    }
  });

  /* ---- Animated stat counters ---- */
  var counters = document.querySelectorAll('.num[data-count]');
  var counted = false;
  function runCounters(){
    if(counted) return; counted = true;
    counters.forEach(function(el){
      var target = parseFloat(el.getAttribute('data-count'));
      var decimals = parseInt(el.getAttribute('data-decimals') || '0', 10);
      var suffix = el.getAttribute('data-suffix') || '';
      var start = 0, duration = 1100, startTime = null;
      function step(ts){
        if(!startTime) startTime = ts;
        var progress = Math.min((ts - startTime) / duration, 1);
        var eased = 1 - Math.pow(1 - progress, 3);
        var val = start + (target - start) * eased;
        el.textContent = val.toFixed(decimals) + suffix;
        if(progress < 1) requestAnimationFrame(step);
      }
      requestAnimationFrame(step);
    });
  }
  var statsSection = document.querySelector('.stats');
  if('IntersectionObserver' in window){
    var io = new IntersectionObserver(function(entries){
      entries.forEach(function(entry){ if(entry.isIntersecting) runCounters(); });
    }, {threshold:0.4});
    io.observe(statsSection);
  } else { runCounters(); }

  /* ---- Simple EN / FR toggle ---- */
  var STRINGS = {
    en: {
      hero_h1_pre:'Find the medicines you need in ', hero_h1_accent:'Kigali.',
      hero_lede:'Real-time information from pharmacies across Kigali, helping you access the right medicines, faster and easier.',
      hero_search_ph:'Search for a medicine, e.g. Amoxicillin 500mg',
      hero_search_btn:'Search', hero_or:'or', hero_upload:'Upload prescription',
      hero_upload_note:'Take a photo or upload a prescription to find available medicines',
      stat1_lbl:'Pharmacies in Kigali', stat1_sub:'and growing',
      stat2_lbl:'Medicines tracked', stat2_sub:'in real time',
      stat3_lbl:'Availability accuracy', stat3_sub:'Trusted data',
      stat4_num:'All districts', stat4_lbl:'of Kigali', stat4_sub:'Connected',
      aud_h2:'Built for everyone in the medicine chain',
      aud_p:'Whoever you are, ApexRx gives you the information you need to act with confidence.',
      aud1_h3:'For Patients', aud1_p:'Find nearby pharmacies and avoid unnecessary trips.',
      aud2_h3:'For Pharmacies', aud2_p:'Manage inventory and reach more patients.',
      aud3_h3:'For Healthcare Professionals', aud3_p:'Check medicine availability to make informed decisions.',
      aud4_h3:'For Suppliers', aud4_p:'Connect with pharmacies and respond to demand.',
      aud_learn:'Learn more →',
      how_h2:'From search to access, in three simple steps',
      how_p:'A visitor never needs an explanation — the path from question to medicine is always this short.',
      how1_h3:'Search', how1_p:'Look for a medicine or upload a prescription.',
      how2_h3:'Check availability', how2_p:'See real-time stock at nearby pharmacies.',
      how3_h3:'Get your medicine', how3_p:'Visit the pharmacy or request a supplier.',
      footer_tag:'Healthy Communities. Brighter Tomorrow. Made for a healthier Rwanda.'
    },
    fr: {
      hero_h1_pre:'Trouvez les médicaments dont vous avez besoin à ', hero_h1_accent:'Kigali.',
      hero_lede:'Des informations en temps réel venant des pharmacies de Kigali, pour accéder plus vite et plus facilement aux bons médicaments.',
      hero_search_ph:'Recherchez un médicament, ex. Amoxicilline 500mg',
      hero_search_btn:'Rechercher', hero_or:'ou', hero_upload:'Envoyer une ordonnance',
      hero_upload_note:'Prenez une photo ou envoyez une ordonnance pour trouver les médicaments disponibles',
      stat1_lbl:'Pharmacies à Kigali', stat1_sub:'en croissance',
      stat2_lbl:'Médicaments suivis', stat2_sub:'en temps réel',
      stat3_lbl:'Précision des stocks', stat3_sub:'Données fiables',
      stat4_num:'Tous les districts', stat4_lbl:'de Kigali', stat4_sub:'Connectés',
      aud_h2:'Pensé pour chaque acteur de la chaîne du médicament',
      aud_p:'Quel que soit votre rôle, ApexRx vous donne les informations nécessaires pour agir en confiance.',
      aud1_h3:'Pour les patients', aud1_p:'Trouvez les pharmacies proches et évitez les déplacements inutiles.',
      aud2_h3:'Pour les pharmacies', aud2_p:'Gérez votre stock et touchez davantage de patients.',
      aud3_h3:'Pour les professionnels de santé', aud3_p:'Vérifiez la disponibilité des médicaments pour décider en connaissance de cause.',
      aud4_h3:'Pour les fournisseurs', aud4_p:'Connectez-vous aux pharmacies et répondez à la demande.',
      aud_learn:'En savoir plus →',
      how_h2:'De la recherche à l’accès, en trois étapes simples',
      how_p:'Un visiteur n’a jamais besoin d’explication — le chemin entre la question et le médicament reste toujours aussi court.',
      how1_h3:'Rechercher', how1_p:'Cherchez un médicament ou envoyez une ordonnance.',
      how2_h3:'Vérifier la disponibilité', how2_p:'Consultez le stock en temps réel des pharmacies proches.',
      how3_h3:'Obtenir votre médicament', how3_p:'Rendez-vous en pharmacie ou sollicitez un fournisseur.',
      footer_tag:'Healthy Communities. Brighter Tomorrow. Conçu pour un Rwanda en meilleure santé.'
    }
  };

  var heroH1 = document.querySelector('.hero h1');
  var heroAccent = heroH1.querySelector('.accent');

  function applyLang(lang){
    var dict = STRINGS[lang];
    heroH1.childNodes[0].textContent = dict.hero_h1_pre;
    heroAccent.textContent = dict.hero_h1_accent;
    document.querySelectorAll('[data-i18n]').forEach(function(el){
      var key = el.getAttribute('data-i18n');
      if(dict[key] !== undefined) el.textContent = dict[key];
    });
    document.querySelectorAll('[data-i18n-placeholder]').forEach(function(el){
      var key = el.getAttribute('data-i18n-placeholder');
      if(dict[key] !== undefined) el.setAttribute('placeholder', dict[key]);
    });
    document.documentElement.lang = lang;
  }

  var langSelect = document.getElementById('langSelect');
  langSelect.value = 'en';
  langSelect.addEventListener('change', function(){ applyLang(langSelect.value); });

  /* ---- Pin cards on touch devices: tap to toggle ---- */
  document.querySelectorAll('.pin').forEach(function(pin){
    pin.addEventListener('click', function(){
      var already = pin.classList.contains('show-card');
      document.querySelectorAll('.pin.show-card').forEach(function(p){ if(p!==pin) p.classList.remove('show-card'); });
      pin.classList.toggle('show-card', !already);
    });
  });
})();
