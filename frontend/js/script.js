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
      btn_signin:'Sign in', btn_start:'Get started', btn_signout:'Sign out', signed_in_as:'Signed in as',
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
      t_updated:'Updated', t_searching:'Searching...', t_search_error:'Unable to load medicine availability. Please try again.',
      // Expanded patient search (search.html, js/patient-search.js)
      ps_see_more:'See more: compare prices, filter by location and get directions →',
      ps_title:'Compare pharmacies',
      ps_eyebrow:'Medicine search',
      ps_lede:'Compare prices, find a pharmacy near you and get directions.',
      ps_back:'← Back to search',
      ps_filters:'Filter and sort',
      ps_min:'Min price',
      ps_max:'Max price',
      ps_sort:'Sort by',
      ps_sort_price:'Lowest price',
      ps_sort_price_desc:'Highest price',
      ps_sort_distance:'Nearest first',
      ps_sort_fresh:'Recently updated',
      ps_location:'Location',
      ps_use_location:'Use my location',
      ps_place_ph:'Or type a place, e.g. Kimironko',
      ps_find:'Find',
      ps_clear:'Clear',
      ps_locating:'Finding your location…',
      ps_loc_denied:'Location permission was denied. You can type a place instead.',
      ps_loc_unavailable:'Your location is not available on this device. You can type a place instead.',
      ps_loc_current:'Your current location',
      ps_loc_map:'The point you chose on the map',
      ps_place_none:'No place in Rwanda matches that name.',
      ps_place_error:'Place search is not available right now. Try again, or use your location.',
      ps_place_pick:'Choose the place:',
      ps_distance:'Distance',
      ps_any_distance:'Any distance',
      ps_within:'Within {n} km',
      ps_needs_location:'Set a location to filter by distance.',
      ps_reset:'Reset filters',
      ps_count_one:'1 pharmacy',
      ps_count:'{n} pharmacies',
      ps_count_of:'Showing {a} of {n} pharmacies',
      ps_empty:'No pharmacy matches these filters. Try a wider price range or distance.',
      ps_no_query:'Search for a medicine to compare pharmacies.',
      ps_err_range:'The minimum price cannot be higher than the maximum.',
      ps_err_price:'Prices must be numbers of 0 or more.',
      ps_load_more:'Show more pharmacies',
      ps_km:'{n} km away',
      ps_no_coords:'No map location',
      ps_cheapest:'Lowest price',
      ps_view:'View pharmacy and directions',
      ps_back_results:'← Back to results',
      ps_phone:'Phone',
      ps_address:'Address',
      ps_searched:'You searched for',
      ps_other_meds:'Medicines listed here',
      ps_start:'Starting point',
      ps_by_car:'By car',
      ps_on_foot:'On foot',
      ps_route_summary:'{d} km · about {m} min',
      ps_route_fail:'The route could not be calculated right now. The map shows a straight line; the directions buttons still work.',
      ps_route_loading:'Calculating the route…',
      ps_start_hint:'Choose a starting point to see the route: use your location, type a place, or tap the map.',
      ps_open_google:'Directions in Google Maps',
      ps_open_osm:'Directions in OpenStreetMap',
      ps_no_map:'This pharmacy has not added its map location yet. Directions use its address.',
      ps_no_address:'This pharmacy has no map location or address yet. Call them for directions.',
      ps_privacy:'Your location stays in this tab. It is used only to find nearby pharmacies and to calculate the route (OpenStreetMap services). ApexRX does not store it.',
      ps_not_found:'This pharmacy is not listed any more.',
      ps_tap_map:'Tap the map to set your starting point.',
      ps_you:'You are here',
      ps_loading:'Loading…',
      ps_call:'Call'
    },
    fr: {
      stats_eyebrow:'ApexRX en chiffres', stats_title:'Une ville. Mieux connectée.',
      stat_districts:'districts',
      motion_pause:'Mettre les images en pause', motion_resume:'Animer les images',
      community_tag:'Plus près des soins.', community_caption:'Relier les habitants, les pharmacies et les possibilités.', how_map_label:'Une ville. Un réseau de pharmacies connecté.', footer_invite:'Un meilleur accès commence par un lien.', footer_connect:'Restons en contact ↗',
      nav_patients:'Patients', nav_pharmacies:'Pharmacies', nav_suppliers:'Fournisseurs', nav_how:'Comment ça marche', nav_about:'À propos',
      btn_signin:'Se connecter', btn_start:'Commencer', btn_signout:'Se déconnecter', signed_in_as:'Connecté en tant que',
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
      t_updated:'Mis à jour', t_searching:'Recherche...', t_search_error:'Impossible de charger la disponibilité. Veuillez réessayer.',
      // Expanded patient search (search.html, js/patient-search.js)
      ps_see_more:'Voir plus : comparer les prix, filtrer par lieu et obtenir l’itinéraire →',
      ps_title:'Comparer les pharmacies',
      ps_eyebrow:'Recherche de médicament',
      ps_lede:'Comparez les prix, trouvez une pharmacie près de vous et obtenez l’itinéraire.',
      ps_back:'← Retour à la recherche',
      ps_filters:'Filtrer et trier',
      ps_min:'Prix min.',
      ps_max:'Prix max.',
      ps_sort:'Trier par',
      ps_sort_price:'Prix le plus bas',
      ps_sort_price_desc:'Prix le plus élevé',
      ps_sort_distance:'Les plus proches',
      ps_sort_fresh:'Mis à jour récemment',
      ps_location:'Lieu',
      ps_use_location:'Utiliser ma position',
      ps_place_ph:'Ou saisissez un lieu, ex. Kimironko',
      ps_find:'Chercher',
      ps_clear:'Effacer',
      ps_locating:'Recherche de votre position…',
      ps_loc_denied:'L’accès à votre position a été refusé. Vous pouvez saisir un lieu à la place.',
      ps_loc_unavailable:'Votre position n’est pas disponible sur cet appareil. Vous pouvez saisir un lieu à la place.',
      ps_loc_current:'Votre position actuelle',
      ps_loc_map:'Le point choisi sur la carte',
      ps_place_none:'Aucun lieu au Rwanda ne correspond à ce nom.',
      ps_place_error:'La recherche de lieu est indisponible pour le moment. Réessayez ou utilisez votre position.',
      ps_place_pick:'Choisissez le lieu :',
      ps_distance:'Distance',
      ps_any_distance:'Toute distance',
      ps_within:'À moins de {n} km',
      ps_needs_location:'Indiquez un lieu pour filtrer par distance.',
      ps_reset:'Réinitialiser les filtres',
      ps_count_one:'1 pharmacie',
      ps_count:'{n} pharmacies',
      ps_count_of:'{a} sur {n} pharmacies affichées',
      ps_empty:'Aucune pharmacie ne correspond à ces filtres. Élargissez la fourchette de prix ou la distance.',
      ps_no_query:'Recherchez un médicament pour comparer les pharmacies.',
      ps_err_range:'Le prix minimum ne peut pas dépasser le prix maximum.',
      ps_err_price:'Les prix doivent être des nombres positifs ou nuls.',
      ps_load_more:'Afficher plus de pharmacies',
      ps_km:'à {n} km',
      ps_no_coords:'Pas de position sur la carte',
      ps_cheapest:'Prix le plus bas',
      ps_view:'Voir la pharmacie et l’itinéraire',
      ps_back_results:'← Retour aux résultats',
      ps_phone:'Téléphone',
      ps_address:'Adresse',
      ps_searched:'Vous avez cherché',
      ps_other_meds:'Médicaments disponibles ici',
      ps_start:'Point de départ',
      ps_by_car:'En voiture',
      ps_on_foot:'À pied',
      ps_route_summary:'{d} km · environ {m} min',
      ps_route_fail:'L’itinéraire n’a pas pu être calculé. La carte montre une ligne droite ; les boutons d’itinéraire fonctionnent toujours.',
      ps_route_loading:'Calcul de l’itinéraire…',
      ps_start_hint:'Choisissez un point de départ pour voir l’itinéraire : votre position, un lieu saisi ou un point sur la carte.',
      ps_open_google:'Itinéraire dans Google Maps',
      ps_open_osm:'Itinéraire dans OpenStreetMap',
      ps_no_map:'Cette pharmacie n’a pas encore indiqué sa position sur la carte. L’itinéraire utilise son adresse.',
      ps_no_address:'Cette pharmacie n’a pas encore de position ni d’adresse. Appelez-la pour l’itinéraire.',
      ps_privacy:'Votre position reste dans cet onglet. Elle sert uniquement à trouver les pharmacies proches et à calculer l’itinéraire (services OpenStreetMap). ApexRX ne l’enregistre pas.',
      ps_not_found:'Cette pharmacie n’est plus listée.',
      ps_tap_map:'Touchez la carte pour choisir votre point de départ.',
      ps_you:'Vous êtes ici',
      ps_loading:'Chargement…',
      ps_call:'Appeler'
    },
    /* Kinyarwanda: à faire relire par un locuteur natif avant la mise en ligne */
    rw: {
      stats_eyebrow:'ApexRX mu mibare', stats_title:'Umujyi umwe. Turushaho guhuzwa.',
      stat_districts:'uturere',
      motion_pause:'Hagarika amashusho', motion_resume:'Komeza amashusho',
      community_tag:'Hafi y’ubuvuzi.', community_caption:'Guhuza abantu na farumasi.', how_map_label:'Umujyi umwe. Farumasi zihujwe.', footer_invite:'Guhuzwa bituma kubona imiti byoroha.', footer_connect:'Tuvugishe ↗',
      nav_patients:'Abarwayi', nav_pharmacies:'Farumasi', nav_suppliers:'Abatanga imiti', nav_how:'Uko bikora', nav_about:'Abo turi bo',
      btn_signin:'Injira', btn_start:'Tangira', btn_signout:'Sohoka', signed_in_as:'Winjiye nka',
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
      t_updated:'Byavuguruwe', t_searching:'Turashakisha...', t_search_error:'Ntibishobotse kubona amakuru y’imiti. Ongera ugerageze.',
      // Expanded patient search (search.html, js/patient-search.js)
      ps_see_more:'Reba ibindi: gereranya ibiciro, shungura ukurikije aho uri, ubone inzira →',
      ps_title:'Gereranya farumasi',
      ps_eyebrow:'Gushaka umuti',
      ps_lede:'Gereranya ibiciro, ubone farumasi ikwegereye n’inzira yo kuyigeraho.',
      ps_back:'← Subira ku ishakisha',
      ps_filters:'Shungura no gutondeka',
      ps_min:'Igiciro gito',
      ps_max:'Igiciro kinini',
      ps_sort:'Tondeka ukurikije',
      ps_sort_price:'Igiciro gito mbere',
      ps_sort_price_desc:'Igiciro kinini mbere',
      ps_sort_distance:'Ziri hafi mbere',
      ps_sort_fresh:'Izavuguruwe vuba',
      ps_location:'Aho uri',
      ps_use_location:'Koresha aho ndi',
      ps_place_ph:'Cyangwa andika ahantu, urugero Kimironko',
      ps_find:'Shaka',
      ps_clear:'Siba',
      ps_locating:'Turashaka aho uri…',
      ps_loc_denied:'Wanze ko tumenya aho uri. Ushobora kwandika ahantu.',
      ps_loc_unavailable:'Aho uri ntibishoboka kumenyekana kuri iki gikoresho. Ushobora kwandika ahantu.',
      ps_loc_current:'Aho uri ubu',
      ps_loc_map:'Aho wahisemo ku ikarita',
      ps_place_none:'Nta hantu mu Rwanda hahuye n’iryo zina.',
      ps_place_error:'Gushaka ahantu ntibishoboka ubu. Ongera ugerageze cyangwa ukoreshe aho uri.',
      ps_place_pick:'Hitamo ahantu:',
      ps_distance:'Intera',
      ps_any_distance:'Intera iyo ari yo yose',
      ps_within:'Muri km {n}',
      ps_needs_location:'Shyiraho aho uri kugira ngo ushungure ukurikije intera.',
      ps_reset:'Siba ibyo washunguye',
      ps_count_one:'Farumasi 1',
      ps_count:'Farumasi {n}',
      ps_count_of:'Herekanwa {a} kuri farumasi {n}',
      ps_empty:'Nta farumasi ihuye n’ibyo wahisemo. Gerageza igiciro cyangwa intera binini.',
      ps_no_query:'Shaka umuti kugira ngo ugereranye farumasi.',
      ps_err_range:'Igiciro gito ntigishobora kuruta igiciro kinini.',
      ps_err_price:'Ibiciro bigomba kuba imibare ingana na 0 cyangwa irenga.',
      ps_load_more:'Erekana farumasi nyinshi',
      ps_km:'km {n} uvuye aho uri',
      ps_no_coords:'Nta hantu ku ikarita',
      ps_cheapest:'Igiciro gito',
      ps_view:'Reba farumasi n’inzira',
      ps_back_results:'← Subira ku bisubizo',
      ps_phone:'Telefoni',
      ps_address:'Aderesi',
      ps_searched:'Washatse',
      ps_other_meds:'Imiti iboneka hano',
      ps_start:'Aho uhagurukira',
      ps_by_car:'Mu modoka',
      ps_on_foot:'N’amaguru',
      ps_route_summary:'km {d} · iminota nka {m}',
      ps_route_fail:'Inzira ntiyabashije kubarwa ubu. Ikarita irerekana umurongo ugororotse; utubuto tw’inzira turakora.',
      ps_route_loading:'Turabara inzira…',
      ps_start_hint:'Hitamo aho uhagurukira kugira ngo ubone inzira: aho uri, ahantu wanditse, cyangwa kanda ku ikarita.',
      ps_open_google:'Inzira kuri Google Maps',
      ps_open_osm:'Inzira kuri OpenStreetMap',
      ps_no_map:'Iyi farumasi ntirashyira aho iherereye ku ikarita. Inzira ikoresha aderesi yayo.',
      ps_no_address:'Iyi farumasi nta hantu ku ikarita cyangwa aderesi irashyiraho. Bahamagare ubaze inzira.',
      ps_privacy:'Aho uri biguma muri iyi paji. Bikoreshwa gusa mu gushaka farumasi zikwegereye no kubara inzira (serivisi za OpenStreetMap). ApexRX ntibibika.',
      ps_not_found:'Iyi farumasi ntikiri ku rutonde.',
      ps_tap_map:'Kanda ku ikarita uhitemo aho uhagurukira.',
      ps_you:'Uri hano',
      ps_loading:'Birimo gufunguka…',
      ps_call:'Hamagara'
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
    document.getElementById(id).addEventListener('click', function(){
      openAccountFlow(window.ApexAPI && ApexAPI.session.isSignedIn() ? '' : '#signin');
    });
  });
  ['getStartedBtn','getStartedBtnMobile'].forEach(function(id){
    document.getElementById(id).addEventListener('click', function(){
      // Signed in: this button signs out (only this session; see js/api.js).
      if (window.ApexAPI && ApexAPI.session.isSignedIn()) { ApexAPI.auth.logout(); return; }
      openAccountFlow('');
    });
  });
  // When this tab is signed in, the header says who it is: "Sign in" becomes
  // the account (opening the workspace) and "Get started" becomes "Sign out".
  function paintAccountButtons(){
    var api = window.ApexAPI, email = api && api.session.isSignedIn() && api.session.email();
    var signedIn = !!(api && api.session.isSignedIn());
    ['signInBtn','signInBtnMobile'].forEach(function(id){
      var b = document.getElementById(id);
      if (signedIn) {
        b.removeAttribute('data-i18n');
        b.textContent = email || t('signed_in_as');
        b.title = t('signed_in_as') + ' ' + (email || '');
        b.classList.add('signed-in-chip');
      } else {
        b.setAttribute('data-i18n', 'btn_signin'); b.textContent = t('btn_signin'); b.removeAttribute('title');
        b.classList.remove('signed-in-chip');
      }
    });
    ['getStartedBtn','getStartedBtnMobile'].forEach(function(id){
      var b = document.getElementById(id);
      b.setAttribute('data-i18n', signedIn ? 'btn_signout' : 'btn_start');
      b.textContent = t(signedIn ? 'btn_signout' : 'btn_start');
    });
  }
  window.addEventListener('apexrx:signed-out', function(){ paintAccountButtons(); toast(t('btn_signout') + ' ✓'); });

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


  /* The hero map exists only on the landing page; other public pages
     (how-it-works.html, about.html, legal.html) share this script for the
     header, footer, menu and translations. */
  var labelHeroPins = function(){};
  if(document.getElementById('mapLayer') && document.getElementById('mapFx')) initHeroMap();
  function initHeroMap(){
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
  labelHeroPins = labelPins;
  }

  /* ================= LANGUAGE ================= */
  var h1Pre = document.getElementById('h1Pre'), h1Accent = document.getElementById('h1Accent');
  function applyLang(l){
    lang = STRINGS[l] ? l : 'en';
    if(h1Pre && h1Accent){ h1Pre.textContent = t('h1_pre'); h1Accent.textContent = t('h1_accent'); }
    document.querySelectorAll('[data-i18n]').forEach(function(el){ el.textContent = t(el.getAttribute('data-i18n')); });
    document.querySelectorAll('[data-i18n-placeholder]').forEach(function(el){ el.setAttribute('placeholder', t(el.getAttribute('data-i18n-placeholder'))); });
    document.documentElement.lang = lang === 'rw' ? 'rw' : lang;
    labelHeroPins();
    try{ localStorage.setItem('apexrx_lang', lang); }catch(e){}
    // Carry the language to the registration pages, keeping any #signin.
    document.querySelectorAll('a[href^="pharmacies.html"], a[href^="suppliers.html"]').forEach(function(a){
      var raw = a.getAttribute('href'), hash = raw.indexOf('#') === -1 ? '' : raw.slice(raw.indexOf('#'));
      a.setAttribute('href', raw.split(/[?#]/)[0] + '?lang=' + encodeURIComponent(lang) + hash);
    });
    paintAccountButtons();
    try { window.dispatchEvent(new CustomEvent('apexrx:lang', { detail: lang })); } catch (e) { /* old browsers */ }
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

  // The expanded results page (search.html) for this query, in the current language.
  function expandedHref(query){
    return 'search.html?q=' + encodeURIComponent(query) + '&lang=' + encodeURIComponent(lang);
  }

  if (searchForm && searchInput && searchResults && searchStatus && window.ApexAPI) {
    // Set when the search comes from the address bar (search.html's "Back to search"):
    // it repeats a search already counted, so it is not counted again.
    var repeatSearch = false;
    searchForm.addEventListener('submit', function (event) {
      event.preventDefault();
      var record = !repeatSearch; repeatSearch = false;
      var query = searchInput.value.trim();
      if (query.length < 2) { searchInput.focus(); return; }

      if (activeSearch) activeSearch.abort();
      var controller = typeof AbortController === 'function' ? new AbortController() : null;
      activeSearch = controller;

      searchStatus.textContent = t('t_searching');
      searchResults.classList.add('open');
      searchResults.replaceChildren();

      var params = { q: query, sort: 'freshness', limit: 20 };
      if (!record) params.record = false;
      ApexAPI.search.pharmacies(params, { signal: controller ? controller.signal : undefined })
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
          // The homepage stays short; comparing, filtering and directions are on search.html.
          var more = document.createElement('a');
          more.className = 'result-more';
          more.id = 'medicineSearchMore';
          more.href = expandedHref(query);
          more.textContent = t('ps_see_more');
          searchResults.appendChild(more);
        })
        .catch(function (error) {
          if (controller && controller.signal.aborted && activeSearch !== controller) return;
          console.error('Medicine search failed:', error);
          searchStatus.textContent = (error && error.status === 0) ? error.message : t('t_search_error');
        });
    });
    // index.html?q=... (search.html's "Back to search") shows that search again.
    var fromUrl = '';
    try { fromUrl = (new URLSearchParams(location.search).get('q') || '').trim(); } catch (e) { /* ignore */ }
    if (fromUrl.length >= 2) {
      searchInput.value = fromUrl.slice(0, 100);
      repeatSearch = true;
      if (typeof searchForm.requestSubmit === 'function') searchForm.requestSubmit(); else searchForm.dispatchEvent(new Event('submit', { cancelable: true }));
    }
  }

  // For page scripts that share this page's language and formats (js/patient-search.js).
  window.ApexSite = {
    t: t,
    lang: function () { return lang; },
    locale: function () { return LOCALES[lang] || 'en-GB'; },
    formatPrice: formatPrice,
    formatAge: formatAge,
    medicineLabel: medicineLabel,
    stockClass: function (status) { return STOCK_CLASS[status] || STOCK_CLASS.in_stock; }
  };
})();
