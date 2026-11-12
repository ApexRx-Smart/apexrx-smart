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
      f_rights:'© 2026 ApexRX_Smart. All rights reserved.', about_h1:'About ApexRX_Smart', about_hero:'Better access to medicine information for everyone in the medicine chain: patients, healthcare professionals, pharmacies and suppliers.', about_chip1:'Patients', about_chip2:'Healthcare professionals', about_chip3:'Pharmacies', about_chip4:'Suppliers', about_who:'— Who we are', about_p1:'ApexRX_Smart is a digital healthcare platform built in Kigali. It shows where medicines are available, so that patients and the professionals who care for them can find a medicine quickly and reliably, close to home.', about_p2:'Behind every search, pharmacies keep their stock and prices up to date and source medicines from verified suppliers. ApexRX connects these links of the medicine chain without replacing the systems they already use.', about_matters:'— Why it matters', about_matters_h:'Finding a medicine should not be a guessing game', about_matters_p:'Medicine availability is often hard to know. Patients, healthcare professionals, pharmacies and suppliers face delays, uncertainty and missed opportunities because information about where medicines are, and how to get them, is limited and scattered.', about_for:'— Who it’s for', about_for_h:'One platform for the whole medicine chain', about_r1_h:'Patients', about_r1_p:'Find out where your medicine is available before you leave home.', about_r1_1:'Search a medicine by name, with no account', about_r1_2:'See nearby pharmacies: in stock, low stock or unavailable', about_r1_3:'Compare prices and distance, and see how fresh the information is', about_r1_cta:'Find a medicine', about_r2_h:'Doctors and healthcare professionals', about_r2_p:'Get reliable availability information to support better treatment decisions for your patients.', about_r2_1:'Check whether a medicine is available nearby before prescribing', about_r2_2:'Tell patients which pharmacies have it, and at what price', about_r2_3:'Search freely, with no account and no patient data', about_r2_cta:'Check availability', about_r3_h:'Pharmacies', about_r3_p:'Make your stock visible to patients and source medicines more efficiently.', about_r3_1:'Publish your stock and prices; patients see availability, never quantities', about_r3_2:'See suppliers’ stock and prices in real time, before going to a depot', about_r3_3:'Follow each order, and manage branches and staff accounts', about_r3_cta:'Register your pharmacy', about_r4_h:'Medicine suppliers', about_r4_p:'Reach verified pharmacies, respond to their requests and have medicines ready when they come.', about_r4_1:'List your catalogue, prices and stock for verified pharmacies', about_r4_2:'Receive requests, send offers, accept or decline orders', about_r4_3:'Confirm each request and have the order ready for pickup', about_r4_cta:'Register as a supplier', about_flow:'— How it connects', about_flow_h:'From a search to a medicine in hand', about_f1_h:'Search', about_f1_p:'A patient or a doctor looks for a medicine.', about_f2_h:'Find a pharmacy', about_f2_p:'ApexRX shows nearby pharmacies that have it.', about_f3_h:'Request', about_f3_p:'The pharmacy compares suppliers’ stock and prices, then sends its request to the right depot.', about_f4_h:'Pick up', about_f4_p:'The supplier confirms and prepares the order, and the pharmacist collects it at the depot.', about_mission_e:'— Our mission', about_mission_h:'Our Mission', about_mission:'To make medicine availability visible and reliable for everyone in the medicine chain, so that patients get the right medicine faster, healthcare professionals decide with confidence, and pharmacies and suppliers serve them better.', about_vision_e:'— Our vision', about_vision_h:'Our Vision', about_vision:'A Rwanda where no one goes from pharmacy to pharmacy looking for a medicine, where every prescription can be filled close to home, and where every pharmacy plans its stock with confidence.', about_values:'— What guides us', about_values_h:'Our values', about_v1_h:'Trust', about_v1_p:'Every pharmacy and supplier is reviewed by our team, with its registration documents, before it can trade on the platform.', about_v2_h:'Privacy', about_v2_p:'Anyone can search without an account. People see whether a medicine is available, never a pharmacy’s exact quantities.', about_v3_h:'Accuracy', about_v3_p:'Every result shows when the stock was last confirmed, so people know how fresh the information is.', about_v4_h:'Access for everyone', about_v4_p:'The platform works on a phone and is available in Kinyarwanda, English and French.', about_team:'— Our team', about_team_h:'Our Team', about_team_p:'The people building ApexRX_Smart.', about_org:'— Our organization', about_org_h:'Our Organization', about_story_h:'Our story', about_story_p:'ApexRX_Smart started from two questions asked every day in Kigali. Patients and doctors ask: where can this medicine be found today? Pharmacies ask: which supplier has it, and at what price? Instead of going from depot to depot, pharmacists now see suppliers’ stock and prices in real time, and know where to buy before they travel.', about_where_h:'Where we work', about_where_p:'We start in Kigali, across Gasabo, Kicukiro and Nyarugenge, with the goal of serving the whole of Rwanda.', about_contact_h:'Get in touch', about_contact_p:'Pharmacy owner, supplier, health professional or partner? Follow us and send us a message:',
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
      f_rights:'© 2026 ApexRX_Smart. Tous droits réservés.', about_h1:'À propos d’ApexRX_Smart', about_hero:'Un meilleur accès à l’information sur les médicaments pour toute la chaîne : patients, professionnels de santé, pharmacies et fournisseurs.', about_chip1:'Patients', about_chip2:'Professionnels de santé', about_chip3:'Pharmacies', about_chip4:'Fournisseurs', about_who:'— Qui nous sommes', about_p1:'ApexRX_Smart est une plateforme de santé numérique conçue à Kigali. Elle montre où les médicaments sont disponibles, pour que les patients et les professionnels qui les soignent trouvent un médicament vite et de façon fiable, près de chez eux.', about_p2:'Derrière chaque recherche, les pharmacies tiennent à jour leur stock et leurs prix, et s’approvisionnent auprès de fournisseurs vérifiés. ApexRX relie ces maillons de la chaîne du médicament sans remplacer les outils qu’ils utilisent déjà.', about_matters:'— Pourquoi c’est important', about_matters_h:'Trouver un médicament ne devrait pas être un jeu de hasard', about_matters_p:'Il est souvent difficile de savoir où trouver un médicament. Patients, professionnels de santé, pharmacies et fournisseurs subissent retards, incertitudes et occasions manquées, parce que l’information sur la disponibilité des médicaments est limitée et dispersée.', about_for:'— Pour qui', about_for_h:'Une plateforme pour toute la chaîne du médicament', about_r1_h:'Patients', about_r1_p:'Sachez où votre médicament est disponible avant de sortir de chez vous.', about_r1_1:'Chercher un médicament par son nom, sans compte', about_r1_2:'Voir les pharmacies proches : en stock, stock faible ou indisponible', about_r1_3:'Comparer prix et distance, et voir si l’information est récente', about_r1_cta:'Trouver un médicament', about_r2_h:'Médecins et professionnels de santé', about_r2_p:'Obtenez une information fiable sur la disponibilité pour mieux décider du traitement de vos patients.', about_r2_1:'Vérifier qu’un médicament est disponible à proximité avant de le prescrire', about_r2_2:'Indiquer aux patients quelles pharmacies l’ont, et à quel prix', about_r2_3:'Chercher librement, sans compte et sans données patient', about_r2_cta:'Vérifier la disponibilité', about_r3_h:'Pharmacies', about_r3_p:'Rendez votre stock visible aux patients et approvisionnez-vous plus efficacement.', about_r3_1:'Publier stock et prix ; les patients voient la disponibilité, jamais les quantités', about_r3_2:'Voir en temps réel le stock et les prix des fournisseurs, avant d’aller au dépôt', about_r3_3:'Suivre chaque commande, gérer succursales et comptes du personnel', about_r3_cta:'Inscrire votre pharmacie', about_r4_h:'Fournisseurs de médicaments', about_r4_p:'Touchez des pharmacies vérifiées, répondez à leurs demandes et tenez les médicaments prêts à leur arrivée.', about_r4_1:'Publier catalogue, prix et stock pour les pharmacies vérifiées', about_r4_2:'Recevoir des demandes, envoyer des offres, accepter ou refuser des commandes', about_r4_3:'Confirmer chaque demande et préparer la commande pour son retrait', about_r4_cta:'S’inscrire comme fournisseur', about_flow:'— Comment tout se relie', about_flow_h:'D’une recherche au médicament en main', about_f1_h:'Chercher', about_f1_p:'Un patient ou un médecin cherche un médicament.', about_f2_h:'Trouver une pharmacie', about_f2_p:'ApexRX montre les pharmacies proches qui l’ont.', about_f3_h:'Demander', about_f3_p:'La pharmacie compare le stock et les prix des fournisseurs, puis envoie sa demande au bon dépôt.', about_f4_h:'Retirer', about_f4_p:'Le fournisseur confirme et prépare la commande, et le pharmacien vient la retirer au dépôt.', about_mission_e:'— Notre mission', about_mission_h:'Notre mission', about_mission:'Rendre la disponibilité des médicaments visible et fiable pour toute la chaîne, afin que les patients obtiennent plus vite le bon médicament, que les professionnels de santé décident en confiance, et que pharmacies et fournisseurs les servent mieux.', about_vision_e:'— Notre vision', about_vision_h:'Notre vision', about_vision:'Un Rwanda où personne ne va de pharmacie en pharmacie pour trouver un médicament, où chaque ordonnance peut être servie près de chez soi, et où chaque pharmacie planifie son stock en confiance.', about_values:'— Ce qui nous guide', about_values_h:'Nos valeurs', about_v1_h:'Confiance', about_v1_p:'Chaque pharmacie et chaque fournisseur est vérifié par notre équipe, sur la base de ses documents d’enregistrement, avant de pouvoir travailler sur la plateforme.', about_v2_h:'Confidentialité', about_v2_p:'Chacun peut chercher sans compte. On voit si un médicament est disponible, jamais les quantités exactes d’une pharmacie.', about_v3_h:'Exactitude', about_v3_p:'Chaque résultat indique quand le stock a été confirmé pour la dernière fois, pour savoir si l’information est récente.', about_v4_h:'Accessible à tous', about_v4_p:'La plateforme fonctionne sur téléphone et existe en kinyarwanda, en anglais et en français.', about_team:'— Notre équipe', about_team_h:'Notre équipe', about_team_p:'Les personnes qui construisent ApexRX_Smart.', about_org:'— Notre organisation', about_org_h:'Notre organisation', about_story_h:'Notre histoire', about_story_p:'ApexRX_Smart est né de deux questions posées chaque jour à Kigali. Patients et médecins demandent : où trouver ce médicament aujourd’hui ? Les pharmacies demandent : quel fournisseur l’a, et à quel prix ? Au lieu d’aller de dépôt en dépôt, les pharmaciens voient en temps réel le stock et les prix des fournisseurs, et savent où acheter avant de se déplacer.', about_where_h:'Où nous travaillons', about_where_p:'Nous commençons à Kigali, dans les districts de Gasabo, Kicukiro et Nyarugenge, avec l’objectif de servir tout le Rwanda.', about_contact_h:'Nous contacter', about_contact_p:'Pharmacien, fournisseur, professionnel de santé ou partenaire ? Suivez-nous et écrivez-nous :',
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
      f_rights:'© 2026 ApexRX_Smart. Uburenganzira bwose burasigasiwe.', about_h1:'Ibyerekeye ApexRX_Smart', about_hero:'Kubona amakuru y’imiti byoroshye kuri bose bari mu ruhererekane rw’imiti: abarwayi, abaganga, farumasi n’abatanga imiti.', about_chip1:'Abarwayi', about_chip2:'Abakozi bo kwa muganga', about_chip3:'Farumasi', about_chip4:'Abatanga imiti', about_who:'— Abo turi bo', about_p1:'ApexRX_Smart ni urubuga rw’ubuzima rw’ikoranabuhanga rwubatswe i Kigali. Rwerekana aho imiti iboneka, kugira ngo abarwayi n’ababitaho babone umuti vuba kandi mu buryo bwizewe, hafi yabo.', about_p2:'Inyuma ya buri gushakisha, farumasi zivugurura stock n’ibiciro byazo kandi zikagura imiti ku batanga imiti bemejwe. ApexRX ihuza izi nzego z’uruhererekane rw’imiti itasimbuye ibikoresho basanzwe bakoresha.', about_matters:'— Impamvu ari ingenzi', about_matters_h:'Gushaka umuti ntibikwiye kuba amahirwe', about_matters_p:'Akenshi biragoye kumenya aho umuti uboneka. Abarwayi, abaganga, farumasi n’abatanga imiti bahura n’ubukererwe, gushidikanya n’amahirwe abura, kubera ko amakuru y’aho imiti iri n’uko yaboneka ari make kandi atatanye.', about_for:'— Ni iya nde', about_for_h:'Urubuga rumwe ku ruhererekane rwose rw’imiti', about_r1_h:'Abarwayi', about_r1_p:'Menya aho umuti wawe uboneka mbere yo kuva mu rugo.', about_r1_1:'Shakisha umuti ukoresheje izina, nta konti', about_r1_2:'Reba farumasi ziri hafi: urahari, urashize, ntawuhari', about_r1_3:'Gereranya ibiciro n’intera, urebe niba amakuru ari mashya', about_r1_cta:'Shakisha umuti', about_r2_h:'Abaganga n’abakozi bo kwa muganga', about_r2_p:'Bona amakuru yizewe y’aho imiti iboneka kugira ngo ufate ibyemezo byiza byo kuvura abarwayi bawe.', about_r2_1:'Reba niba umuti uboneka hafi mbere yo kuwandika', about_r2_2:'Bwira abarwayi farumasi ziwufite n’igiciro', about_r2_3:'Shakisha nta konti kandi nta makuru y’umurwayi', about_r2_cta:'Reba aho uboneka', about_r3_h:'Farumasi', about_r3_p:'Garagariza abarwayi stock yawe kandi ugure imiti mu buryo bworoshye.', about_r3_1:'Shyira ahagaragara stock n’ibiciro; abarwayi babona niba bihari gusa', about_r3_2:'Reba stock n’ibiciro by’abatanga imiti ako kanya, mbere yo kujya ku bubiko', about_r3_3:'Kurikirana buri komande, ucunge amashami na konti z’abakozi', about_r3_cta:'Andikisha farumasi yawe', about_r4_h:'Abatanga imiti', about_r4_p:'Gera kuri farumasi zemejwe, usubize ibyo zisaba kandi utegure imiti mbere y’uko zihagera.', about_r4_1:'Shyira kataloge, ibiciro na stock ku mafarumasi yemejwe', about_r4_2:'Akira ibisabwa, wohereze ibiciro, wemere cyangwa wange amakomande', about_r4_3:'Emeza buri busabe kandi utegure komande kugira ngo izafatwe', about_r4_cta:'Iyandikishe nk’utanga imiti', about_flow:'— Uko bihuzwa', about_flow_h:'Kuva ku gushakisha kugera ku muti mu ntoki', about_f1_h:'Shakisha', about_f1_p:'Umurwayi cyangwa umuganga ashakisha umuti.', about_f2_h:'Bona farumasi', about_f2_p:'ApexRX yerekana farumasi ziri hafi ziwufite.', about_f3_h:'Gusaba', about_f3_p:'Farumasi igereranya stock n’ibiciro by’abatanga imiti, hanyuma ikohereza icyo isaba ku bubiko bukwiye.', about_f4_h:'Gufata', about_f4_p:'Utanga imiti yemeza agategura komande, umufarumasiye akaza kuyifata ku bubiko.', about_mission_e:'— Intego yacu', about_mission_h:'Intego yacu', about_mission:'Kugaragaza neza kandi mu buryo bwizewe aho imiti iboneka ku bari mu ruhererekane rwose, kugira ngo abarwayi babone umuti ukwiye vuba, abaganga bafate ibyemezo bafite icyizere, farumasi n’abatanga imiti babakorere neza kurushaho.', about_vision_e:'— Icyerekezo cyacu', about_vision_h:'Icyerekezo cyacu', about_vision:'U Rwanda aho nta muntu ukizenguruka farumasi ashaka umuti, aho buri rupapuro rwa muganga rubonerwa imiti hafi y’iwabo, kandi aho buri farumasi itegura stock yayo ifite icyizere.', about_values:'— Ibituyobora', about_values_h:'Indangagaciro zacu', about_v1_h:'Icyizere', about_v1_p:'Buri farumasi n’utanga imiti bigenzurwa n’itsinda ryacu hakoreshejwe impapuro zabo mbere yo gukorera ku rubuga.', about_v2_h:'Ibanga', about_v2_p:'Buri wese ashobora gushakisha nta konti. Abantu babona niba umuti uhari, ntibabona ingano nyayo ya farumasi.', about_v3_h:'Ukuri', about_v3_p:'Buri gisubizo cyerekana igihe stock yemerejwe bwa nyuma, kugira ngo abantu bamenye ko amakuru ari mashya.', about_v4_h:'Kuri bose', about_v4_p:'Urubuga rukora kuri telefoni kandi ruboneka mu Kinyarwanda, Icyongereza n’Igifaransa.', about_team:'— Itsinda ryacu', about_team_h:'Itsinda ryacu', about_team_p:'Abantu bubaka ApexRX_Smart.', about_org:'— Ikigo cyacu', about_org_h:'Ikigo cyacu', about_story_h:'Amateka yacu', about_story_p:'ApexRX_Smart yavutse ku bibazo bibiri bibazwa buri munsi i Kigali. Abarwayi n’abaganga barabaza bati: uyu muti waboneka he uyu munsi? Farumasi zirabaza ziti: ni nde utanga imiti uwufite, kandi ku kihe giciro? Aho kuzenguruka ububiko bumwe ku bundi, abafarumasiye babona stock n’ibiciro by’abatanga imiti ako kanya, bakamenya aho bagura mbere yo kugenda.', about_where_h:'Aho dukorera', about_where_p:'Dutangiriye i Kigali, mu turere twa Gasabo, Kicukiro na Nyarugenge, tugamije kugera ku Rwanda rwose.', about_contact_h:'Twandikire', about_contact_p:'Ufite farumasi, utanga imiti, uri umuganga cyangwa umufatanyabikorwa? Dukurikire utwandikire:',
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
