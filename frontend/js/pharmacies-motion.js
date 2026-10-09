(() => {
 'use strict';
 const reduced=window.matchMedia('(prefers-reduced-motion: reduce)');
 const host=document.getElementById('workflow-video');
 const toggle=document.getElementById('background-toggle');
 let playing=false;
 function setVideo(play){
  host.replaceChildren();playing=play;
  if(play){const frame=document.createElement('iframe');frame.src='https://www.youtube-nocookie.com/embed/C0lFNEzLkLA?autoplay=1&mute=1&loop=1&playlist=C0lFNEzLkLA&controls=0&playsinline=1&rel=0';frame.title='Goodlife Pharmacy — background video';frame.tabIndex=-1;frame.allow='autoplay; encrypted-media';frame.referrerPolicy='strict-origin-when-cross-origin';host.append(frame);}
  toggle.textContent=play?'Pause background video':'Play background video';toggle.setAttribute('aria-pressed',String(play));
 }
 toggle.addEventListener('click',()=>setVideo(!playing));setVideo(!reduced.matches);
 reduced.addEventListener('change',()=>{if(reduced.matches)setVideo(false);updateScroll();});
 const input=document.querySelector('[name=code]');
 const cells=[...document.querySelectorAll('.otp-digits>span')];
 function paintCode(){const clean=input.value.replace(/\D/g,'').slice(0,6);if(input.value!==clean)input.value=clean;cells.forEach((cell,i)=>{cell.textContent=clean[i]||'–';cell.classList.toggle('filled',i<clean.length);cell.classList.toggle('current',document.activeElement===input && i===Math.min(input.selectionStart??clean.length,5));});}
 ['input','focus','blur','keyup','click'].forEach(event=>input.addEventListener(event,paintCode));paintCode();
 const blocks=document.querySelectorAll('.story-photo,.overview-cards>*,.data-panel,.plan,.uploads,.location-heading');
 if('IntersectionObserver' in window){const observer=new IntersectionObserver(entries=>entries.forEach(entry=>{if(entry.isIntersecting){entry.target.classList.add('scroll-visible');observer.unobserve(entry.target);}}),{threshold:.12});blocks.forEach((block,i)=>{block.classList.add('scroll-reveal');block.style.setProperty('--reveal-delay',`${(i%3)*70}ms`);observer.observe(block);});}
 let scheduled=false;
 function updateScroll(){scheduled=false;const max=document.documentElement.scrollHeight-innerHeight;document.documentElement.style.setProperty('--page-progress',String(max>0?Math.min(1,scrollY/max):0));document.documentElement.style.setProperty('--scene-offset',reduced.matches?'0px':`${Math.min(scrollY*.08,55)}px`);}
 window.addEventListener('scroll',()=>{if(!scheduled){scheduled=true;requestAnimationFrame(updateScroll);}},{passive:true});window.addEventListener('resize',updateScroll);updateScroll();
})();
