/* ApexRX Smart — patient journey preview.
 * No API calls, persistent patient data, payment, or actual reservation.
 * Only a language preference is stored in localStorage.
 */
(() => {
  'use strict';
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => [...document.querySelectorAll(s)];
  const texts = window.ApexRxPatientTexts || {};
  const data = (window.ApexRxPatientDemo && window.ApexRxPatientDemo.pharmacies) || [];
  const steps = ['#patient-account','#patient-verify','#patient-search','#patient-compare','#patient-reserve'].map($);
  const centers = {
    all:{latitude:-1.9536,longitude:30.0606},
    Gasabo:{latitude:-1.9410,longitude:30.0980},
    Kicukiro:{latitude:-1.9780,longitude:30.0980},
    Nyarugenge:{latitude:-1.9550,longitude:30.0530}
  };
  const state = {language:'en', step:0, name:'',email:'',query:'',district:'all',sort:'price',matches:[],selected:null,reservation:null,view:'home'};
  let notificationTimer;
  const txt = (key, vars={}) => {
    let message = (texts[state.language] || {})[key] ?? (texts.en || {})[key] ?? key;
    return message.replace(/\{(\w+)\}/g, (_,name) => String(vars[name] ?? ''));
  };
  const el = (tag, cls, value) => {const node=document.createElement(tag);if(cls)node.className=cls;if(value!==undefined)node.textContent=String(value);return node;};
  function clear(node){node.replaceChildren();}
  // FE-02: preserve the designed <br>/<em>/<strong> typography without
  // parsing translated strings as HTML. Unknown markup is inert text.
  function renderFormattedTranslation(node, raw){
    clear(node);
    const fragments = String(raw).split(/(<br\s*\/?>|<\/?(?:em|strong)>)/gi);
    const stack = [node];
    fragments.forEach(fragment=>{
      if(!fragment)return;
      const token=fragment.toLowerCase();
      if(/^<br\s*\/?>$/.test(token)){
        stack[stack.length-1].append(document.createElement('br'));
      }else if(token==='<em>'||token==='<strong>'){
        const child=document.createElement(token.slice(1,-1));
        stack[stack.length-1].append(child);stack.push(child);
      }else if(token==='</em>'||token==='</strong>'){
        if(stack.length>1 && stack[stack.length-1].tagName.toLowerCase()===token.slice(2,-1)) stack.pop();
        else stack[stack.length-1].append(document.createTextNode(fragment));
      }else{
        stack[stack.length-1].append(document.createTextNode(fragment));
      }
    });
  }
  function addLine(parent, label, value, wide=false){
    const wrap=el('div','detail'+(wide?' wide':''));const dt=el('dt','',label);const dd=el('dd','',value);
    wrap.append(dt,dd);parent.append(wrap);
  }
  function dayOffset(n){const d=new Date();d.setHours(12,0,0,0);d.setDate(d.getDate()+n);return [d.getFullYear(),String(d.getMonth()+1).padStart(2,'0'),String(d.getDate()).padStart(2,'0')].join('-');}
  function dateLabel(iso){if(!iso)return '—';const [y,m,d]=iso.split('-').map(Number);return new Intl.DateTimeFormat(state.language==='rw'?'rw-RW':state.language==='fr'?'fr-FR':'en-GB',{day:'numeric',month:'long',year:'numeric'}).format(new Date(y,m-1,d));}
  function price(amount){return new Intl.NumberFormat(state.language==='fr'?'fr-FR':'en-GB',{maximumFractionDigits:0}).format(amount)+' RWF';}
  function km(origin, point){const rad=Math.PI/180,dlat=(point.latitude-origin.latitude)*rad,dlon=(point.longitude-origin.longitude)*rad;
    const a=Math.sin(dlat/2)**2+Math.cos(origin.latitude*rad)*Math.cos(point.latitude*rad)*Math.sin(dlon/2)**2;
    return 12742*Math.asin(Math.min(1,Math.sqrt(a)));
  }
  function notice(message){const box=$('#patient-notice');box.textContent=message;box.classList.add('visible');clearTimeout(notificationTimer);notificationTimer=setTimeout(()=>box.classList.remove('visible'),5000);}
  function showError(text,context='#patient-form-error'){const box=$(context);box.textContent=text;if(text)box.focus?.();}
  function activeStep(index, focus=true){
    state.step=index;
    $('#patient-onboarding').hidden=false;$('#patient-dashboard').hidden=true;
    steps.forEach((section,i)=>section.hidden=i!==index);
    $$('.patient-steps li').forEach((item,i)=>{item.classList.toggle('active',i===index);item.classList.toggle('done',i<index);if(i===index)item.setAttribute('aria-current','step');else item.removeAttribute('aria-current');});
    $('#step-caption').textContent=txt('step_caption',{n:String(index+1).padStart(2,'0')});
    $('#step-title').textContent=txt('title'+index);$('#step-description').textContent=txt('desc'+index);
    showError('');if(index===2)showError('','#search-error');
    if(index===4)renderSelection();
    if(index===3)renderResults();
    if(focus){$('#step-title').focus();window.scrollTo({top:0,behavior:'instant'});}
  }
  function setLanguage(value){
    state.language = texts[value]?value:'en';
    document.documentElement.lang=state.language;
    document.title=txt('page_title');
    $$('[data-t]').forEach(node=>{node.textContent=txt(node.dataset.t);});
    $$('[data-t-html]').forEach(node=>renderFormattedTranslation(node,txt(node.dataset.tHtml)));
    $$('[data-t-placeholder]').forEach(node=>{node.placeholder=txt(node.dataset.tPlaceholder);});
    $('#patient-language').value=state.language;
    ['#brand-home','#back-home'].forEach(selector=>$(selector).href='index.html?lang='+encodeURIComponent(state.language));
    try{localStorage.setItem('apexrx_lang',state.language);}catch(error){}
    if(!$('#patient-onboarding').hidden)activeStep(state.step,false);
    else renderDashboard();
  }
  function otpDisplay(){const value=$('#patient-verify input[name="code"]').value;const chars=$$('.otp-digits span');chars.forEach((digit,i)=>{digit.textContent=value[i]||'–';digit.classList.toggle('filled',i<value.length);digit.classList.toggle('current',i===value.length&&i<6);});}
  function createMedicineOptions(){
    const medicines=new Set(data.flatMap(ph=>(ph.medicines||[]).map(m=>m.name)));
    const list=$('#patient-medicine-options');clear(list);
    [...medicines].sort((a,b)=>a.localeCompare(b)).forEach(name=>{const option=document.createElement('option');option.value=name;list.append(option);});
  }
  const normalize=(value)=>String(value||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase().trim();
  function search(){
    if(!data.length){showError(txt('error_data'),'#search-error');return false;}
    state.query=$('#patient-medicine').value.trim();
    state.district=$('#patient-district').value;state.sort=$('#patient-sort').value;
    if(state.query.length<2){showError(txt('error_medicine'),'#search-error');return false;}
    const origin=centers[state.district]||centers.all;
    state.matches=data.flatMap(ph=>{
      if(state.district!=='all'&&ph.district!==state.district)return [];
      const medicine=(ph.medicines||[]).find(m=>normalize(m.name).includes(normalize(state.query))&&m.quantity>0);
      if(!medicine)return [];
      return [{pharmacy:ph,medicine,distance:km(origin,ph)}];
    });
    const sortBy={price:(a,b)=>a.medicine.examplePriceRwf-b.medicine.examplePriceRwf,
      distance:(a,b)=>a.distance-b.distance,stock:(a,b)=>b.medicine.quantity-a.medicine.quantity};
    state.matches.sort((a,b)=>(sortBy[state.sort]||sortBy.price)(a,b)||a.pharmacy.name.localeCompare(b.pharmacy.name));
    if(!state.matches.length){showError(txt('error_no_results'),'#search-error');return false;}
    showError('','#search-error');activeStep(3);return true;
  }
  function renderResults(){
    const container=$('#patient-results');clear(container);
    $('#result-count').textContent=state.matches.length?txt('result_count',{count:state.matches.length,medicine:state.query}):txt('result_zero');
    if(!state.matches.length){container.append(el('p','patient-result empty',txt('error_no_results')));return;}
    state.matches.forEach(item=>{
      const row=el('article','patient-result');const description=el('div');
      description.append(el('span','tag',txt('demo_listing')),
        el('h3','',item.pharmacy.name),el('p','sub',item.pharmacy.district+' · '+item.pharmacy.area),
        el('p','sample',txt('demo_stock',{n:item.medicine.quantity})));
      const cost=el('div','patient-result-price');cost.append(el('strong','',price(item.medicine.examplePriceRwf)),el('small','',txt('example_price')));
      const actions=el('div','result-actions');actions.append(el('span','',txt('approx_distance',{n:item.distance.toFixed(1)})));
      const button=el('button','',txt('view_option'));button.type='button';button.setAttribute('aria-label',txt('view_option')+' '+item.pharmacy.name);
      button.addEventListener('click',()=>{state.selected=item;activeStep(4);});
      actions.append(button);row.append(description,cost,actions);container.append(row);
    });
  }
  function renderSelection(){
    const item=state.selected;const summary=$('#patient-selection-summary');clear(summary);
    if(!item)return;
    summary.append(el('span','',txt('selection_caption')),el('h3','',item.pharmacy.name),
      el('p','',txt('selection_medicine')+': '+item.medicine.name),
      el('p','',txt('selection_area')+': '+item.pharmacy.district+' · '+item.pharmacy.area),
      el('p','',txt('selection_price')+': '+price(item.medicine.examplePriceRwf)));
  }
  function openDashboard(){
    $('#patient-onboarding').hidden=true;$('#patient-dashboard').hidden=false;
    state.view='home';renderDashboard();window.scrollTo({top:0,behavior:'instant'});
  }
  function detailPanel(){
    const wrap=$('#patient-panel-content');clear(wrap);
    const booking=state.reservation;
    if(state.view==='profile'){
      const grid=el('dl','patient-reservation');
      addLine(grid,txt('name_label'),state.name||'—');addLine(grid,txt('account_label'),state.email||'—');
      addLine(grid,txt('source_label'),txt('source_value'),true);wrap.append(grid);return;
    }
    if(!booking){
      const card=el('div','patient-empty');card.append(el('strong','',txt('empty_title')),el('p','',txt('empty_body')));
      wrap.append(card);return;
    }
    const grid=el('dl','patient-reservation');
    addLine(grid,txt('ref_label'),booking.reference);
    addLine(grid,txt('status_label'),txt('demo_status'));
    addLine(grid,txt('medicine_label_short'),booking.medicine.name);
    addLine(grid,txt('pharmacy_label'),booking.pharmacy.name);
    addLine(grid,txt('date_label'),dateLabel(booking.date));
    addLine(grid,txt('time_label'),txt(booking.period));
    addLine(grid,txt('price_label'),price(booking.medicine.examplePriceRwf));
    addLine(grid,txt('area_label'),booking.pharmacy.district+' · '+booking.pharmacy.area);
    wrap.append(grid);
    const note=el('p','patient-legend',txt('disclaimer_result'));note.style.marginTop='18px';wrap.append(note);
    const actions=el('div','patient-panel-actions');
    const clearButton=el('button','',txt('cancel_demo'));clearButton.type='button';clearButton.addEventListener('click',()=>{state.reservation=null;renderDashboard();notice(txt('cancel_notice'));});
    // The link opens a neighborhood search, not a fictitious pharmacy location.
    const mapLink=el('a','',txt('map_area'));mapLink.href='https://www.google.com/maps/search/?api=1&query='+encodeURIComponent(booking.pharmacy.area+', Kigali, Rwanda');
    mapLink.target='_blank';mapLink.rel='noopener noreferrer';
    actions.append(mapLink,clearButton);wrap.append(actions);
  }
  function renderDashboard(){
    $('#patient-today').textContent=new Intl.DateTimeFormat(state.language==='fr'?'fr-FR':state.language==='rw'?'rw-RW':'en-GB',{weekday:'long',day:'numeric',month:'long',year:'numeric'}).format(new Date());
    $('#patient-name').textContent=state.name||txt('guest');
    $('#patient-medicine-count').textContent=state.reservation?.medicine.name||state.query||txt('search_none');
    $('#patient-pharmacy-count').textContent=state.reservation?.pharmacy.area||txt('pharmacy_none');
    $('#patient-reservation-state').textContent=state.reservation?txt('demo_status'):txt('demo_status_none');
    $('#patient-panel-title').textContent=txt('panel_'+state.view);
    $$('[data-patient-view]').forEach(node=>{node.classList.toggle('selected',node.dataset.patientView===state.view);node.setAttribute('aria-current',node.dataset.patientView===state.view?'page':'false');});
    detailPanel();
  }
  function displayView(view){state.view=view;renderDashboard();$('#patient-panel-title').focus();$('#patient-panel-title').scrollIntoView({block:'nearest'});}
  function goSearch(){if(state.reservation?.medicine.name&&!$('#patient-medicine').value)$('#patient-medicine').value=state.reservation.medicine.name;activeStep(2);}
  function init(){
    createMedicineOptions();
    const pickup=$('#patient-pickup-date');pickup.min=dayOffset(0);pickup.max=dayOffset(7);pickup.value=dayOffset(1);
    let lang='en';try{lang=new URLSearchParams(location.search).get('lang')||localStorage.getItem('apexrx_lang')||'en';}catch(e){}
    $('#patient-language').addEventListener('change',e=>setLanguage(e.target.value));
    $$('[data-back]').forEach(button=>button.addEventListener('click',()=>activeStep(Number(button.dataset.back))));
    $('#patient-account').addEventListener('submit',e=>{
      e.preventDefault();const elements=e.currentTarget.elements;
      if(elements.namedItem('password').value!==elements.namedItem('confirm').value){showError(txt('error_mismatch'));elements.namedItem('confirm').focus();return;}
      state.name=elements.namedItem('name').value.trim();state.email=elements.namedItem('email').value.trim();
      $('#patient-email-display').textContent=state.email;
      elements.namedItem('password').value='';elements.namedItem('confirm').value='';
      activeStep(1);
    });
    const otp=$('#patient-verify input[name="code"]');otp.addEventListener('input',()=>{otp.value=otp.value.replace(/\D/g,'').slice(0,6);otpDisplay();});
    $('#patient-verify').addEventListener('submit',e=>{e.preventDefault();if(otp.value!=='472916'){showError(txt('error_code'));otp.focus();return;}activeStep(2);});
    $('#patient-preview').addEventListener('click',()=>{openDashboard();notice(txt('preview_notice'));});
    $('#patient-search').addEventListener('submit',e=>{e.preventDefault();search();});
    $('#patient-edit-search').addEventListener('click',()=>activeStep(2));
    $('#patient-reserve').addEventListener('submit',e=>{
      e.preventDefault();if(!state.selected){activeStep(2);return;}
      if(!$('#patient-confirm-demo').checked){showError(txt('error_confirm'));return;}
      const date=pickup.value;if(!date||date<dayOffset(0)||date>dayOffset(7)){showError(txt('error_date'));return;}
      const period=e.currentTarget.elements.namedItem('period').value;
      state.reservation={reference:'DEMO-'+Date.now().toString(36).toUpperCase().slice(-7),
        pharmacy:state.selected.pharmacy,medicine:state.selected.medicine,date,period};
      openDashboard();notice(txt('booking_success'));
    });
    $$('[data-patient-view]').forEach(node=>node.addEventListener('click',()=>displayView(node.dataset.patientView)));
    ['#patient-new-search','#patient-new-search-side'].forEach(selector=>$(selector).addEventListener('click',goSearch));
    $('#patient-restart').addEventListener('click',()=>{
      state.name='';state.email='';state.query='';state.district='all';state.matches=[];state.selected=null;state.reservation=null;
      $('#patient-account').reset();$('#patient-verify').reset();$('#patient-search').reset();$('#patient-reserve').reset();otpDisplay();activeStep(0);
    });
    setLanguage(lang);otpDisplay();
    const updateScroll=()=>{const root=document.documentElement;const limit=Math.max(1,root.scrollHeight-innerHeight);root.style.setProperty('--page-progress',Math.min(1,scrollY/limit));};
    addEventListener('scroll',updateScroll,{passive:true});updateScroll();
  }
  init();
})();
