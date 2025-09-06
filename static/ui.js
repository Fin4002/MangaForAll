
// Minimal enhancements. No dependencies. Keep it tiny on purpose.
(function(){
  const qs = s => document.querySelector(s);
  const menuBtn = qs('[data-menu]');
  const menu = qs('[data-menu-target]');
  if(menuBtn && menu){
    menuBtn.addEventListener('click', () => menu.classList.toggle('hidden'));
  }

  // Auto-dismiss flash messages
  document.querySelectorAll('.alert[data-autoclose]').forEach(el => {
    const t = parseInt(el.getAttribute('data-autoclose'), 10) || 3500;
    setTimeout(()=> el.classList.add('hidden'), t);
  });
})();
(function () {
  const root = document.getElementById('modal-root');
  if (!root) return;
  const contentEl = document.getElementById('modal-content');

  function show(html, urlForHistory) {
    contentEl.innerHTML = html;
    root.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
    if (urlForHistory) {
      const clean = urlForHistory.replace(/\?partial=1(&|$)/, '$1');
      history.pushState({ modal: true }, '', clean);
    }
  }
  function hide(popHistory = false) {
    root.classList.add('hidden');
    contentEl.innerHTML = '';
    document.body.style.overflow = '';
    if (popHistory) history.back();
  }

  // Open modal
  document.addEventListener('click', async (e) => {
    const a = e.target.closest('[data-modal]');
    if (!a) return;
    e.preventDefault();
    const url = a.getAttribute('href');
    const fetchUrl = url + (url.includes('?') ? '&' : '?') + 'partial=1';
    const res = await fetch(fetchUrl, { headers: { 'X-Requested-With': 'fetch' } });
    show(await res.text(), url);
    // focus first focusable
    const first = contentEl.querySelector('button, [href], input, textarea, select, [tabindex]:not([tabindex="-1"])');
    if (first) first.focus();
  });

  // Close actions
  root.addEventListener('click', (e) => {
    if (e.target.matches('[data-close]')) hide(false);
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !root.classList.contains('hidden')) hide();
  });

  // Ajax submit inside modal
  contentEl.addEventListener('submit', async (e) => {
    const form = e.target.closest('form[data-ajax]');
    if (!form) return;
    e.preventDefault();
    const res = await fetch(form.action, { method: 'POST', body: new FormData(form), headers: { 'X-Requested-With': 'fetch' } });
    contentEl.innerHTML = await res.text();  // re-render partial with new comment
    const ta = contentEl.querySelector('textarea[name="content"]');
    if (ta) ta.focus();
  });

  // Back button closes modal
  window.addEventListener('popstate', () => {
    if (!root.classList.contains('hidden')) {
      root.classList.add('hidden');
      contentEl.innerHTML = '';
      document.body.style.overflow = '';
    }
  });
})();
// ----- Modal controls (robust) -----
(function () {
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

  function openModal(modal) {
    if (modal) modal.classList.add('is-open');
  }
  function closeModal(modal) {
    if (modal) modal.classList.remove('is-open');
  }

  // Openers: <button data-modal-open="#post-modal">
  $$('.modal-open,[data-modal-open]').forEach(btn => {
    btn.addEventListener('click', e => {
      e.preventDefault();
      const sel = btn.getAttribute('data-modal-open') || btn.dataset.modalOpen;
      openModal($(sel));
    });
  });

  // Delegated closers: backdrop or any element inside with [data-modal-close]
  $$('.modal,[data-modal]').forEach(modal => {
    modal.addEventListener('click', e => {
      const onBackdrop = e.target.classList.contains('modal-backdrop');
      const wantsClose = e.target.closest('[data-modal-close]');
      if (onBackdrop || wantsClose) {
        e.preventDefault();
        closeModal(modal);
      }
    });
  });

  // ESC closes the last-open modal
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
      const open = $$('.modal.is-open').pop();
      if (open) closeModal(open);
    }
  });
})();
// ---------- Chapters: progressive reveal ----------
(function () {
  const table = document.querySelector('#chapters-table');
  if (!table) return;

  const rows = Array.from(table.querySelectorAll('tbody tr'));
  const chunk = parseInt(table.dataset.chunk || '30', 10);
  let shown = 0;

  const btnMore = document.querySelector('[data-more]');
  const btnCollapse = document.querySelector('[data-collapse]');

  function render() {
    rows.forEach((r, i) => {
      r.style.display = i < shown ? '' : 'none';
    });

    const remaining = rows.length - shown;

    if (remaining <= 0) {
      // All visible
      if (btnMore) btnMore.classList.add('hidden');
      if (btnCollapse) btnCollapse.classList.remove('hidden');
    } else {
      if (btnMore) {
        btnMore.classList.remove('hidden');
        btnMore.textContent = `Show ${Math.min(chunk, remaining)} more`;
      }
      if (btnCollapse) btnCollapse.classList.toggle('hidden', shown <= chunk);
    }
  }

  function showInitial() {
    shown = Math.min(chunk, rows.length);
    render();
  }

  btnMore && btnMore.addEventListener('click', () => {
    shown = Math.min(shown + chunk, rows.length);
    render();
  });

  btnCollapse && btnCollapse.addEventListener('click', () => {
    shown = Math.min(chunk, rows.length);
    table.scrollIntoView({ behavior: 'smooth', block: 'start' });
    render();
  });

  showInitial();
})();
// ----- Reader fullscreen -----
(function () {
  const docEl = document.documentElement;
  const btns = Array.from(document.querySelectorAll('#fs-btn, #fs-btn-bottom'));

  if (!btns.length) return;

  function inFS() {
    return document.fullscreenElement != null || docEl.classList.contains('fs');
  }

  async function enterFS() {
    try {
      if (!document.fullscreenElement && docEl.requestFullscreen) {
        await docEl.requestFullscreen({ navigationUI: "hide" }).catch(()=>{});
      }
    } catch {}
    docEl.classList.add('fs');
    updateButtons();
  }

  async function exitFS() {
    try {
      if (document.fullscreenElement && document.exitFullscreen) {
        await document.exitFullscreen().catch(()=>{});
      }
    } catch {}
    docEl.classList.remove('fs');
    updateButtons();
  }

  function toggleFS() {
    inFS() ? exitFS() : enterFS();
  }

  function updateButtons() {
    btns.forEach(b => b.textContent = inFS() ? 'Exit Fullscreen' : 'Fullscreen');
  }

  // Click handlers
  btns.forEach(b => b.addEventListener('click', toggleFS));

  // Keyboard: press "f" to toggle
  document.addEventListener('keydown', e => {
    if (e.key.toLowerCase() === 'f') {
      e.preventDefault();
      toggleFS();
    }
  });

  // Sync on system-level FS changes
  document.addEventListener('fullscreenchange', () => {
    if (!document.fullscreenElement) docEl.classList.remove('fs');
    updateButtons();
  });
})();
// ===== Fullscreen toggle for reader (kept small and polite) =====
(function () {
  const docEl = document.documentElement;
  const fsBtn = document.getElementById('fs-btn');
  if (!fsBtn) return;

  function inFS(){ return document.fullscreenElement != null || docEl.classList.contains('fs'); }
  async function enter(){
    try { if (!document.fullscreenElement && docEl.requestFullscreen) await docEl.requestFullscreen({ navigationUI:"hide" }); } catch(e){}
    docEl.classList.add('fs');
    fsBtn.textContent = 'Exit Fullscreen';
  }
  async function exit(){
    try { if (document.fullscreenElement && document.exitFullscreen) await document.exitFullscreen(); } catch(e){}
    docEl.classList.remove('fs');
    fsBtn.textContent = 'Fullscreen';
  }
  function toggle(){ inFS() ? exit() : enter(); }

  fsBtn.addEventListener('click', toggle);
  document.addEventListener('keydown', e => { if (e.key.toLowerCase() === 'f') { e.preventDefault(); toggle(); } });
  document.addEventListener('fullscreenchange', () => { if (!document.fullscreenElement) docEl.classList.remove('fs'); fsBtn.textContent = inFS() ? 'Exit Fullscreen' : 'Fullscreen'; });
})();

// ===== Reader Pop-out (scroll-to-read, draggable, resizable, chapter jumping) =====
(function () {
  const el = document.getElementById('reader-popout');
  const btnToggle = document.getElementById('popout-btn');
  if (!el || !btnToggle) return;

  const btnPrev  = el.querySelector('[data-popout-prev]');
  const btnNext  = el.querySelector('[data-popout-next]');
  const btnClose = el.querySelector('[data-popout-close]');
  const header   = el.querySelector('.popout-header');
  const grip     = el.querySelector('.popout-resize');

  const scroller  = document.getElementById('popout-scroll');
  const pagesWrap = document.getElementById('popout-pages');
  if (!scroller || !pagesWrap) { console.warn('[popout] missing #popout-scroll/#popout-pages'); return; }

  const nextChUrl = el.dataset.nextChUrl || '';
  const prevChUrl = el.dataset.prevChUrl || '';

  let pages = Array.isArray(window.READER_PAGES) ? window.READER_PAGES.slice() : [];
  let idx   = Number.isInteger(window.READER_INDEX) ? window.READER_INDEX : 0;
  idx = Math.max(0, Math.min(idx, Math.max(0, pages.length - 1)));

  // drag/resize state
  let pos = { x: null, y: null, w: 420, h: 320 };
  function clamp(v, min, max){ return Math.max(min, Math.min(max, v)); }
  function getPoint(e){ if (e.touches && e.touches[0]) return { x:e.touches[0].clientX, y:e.touches[0].clientY }; return { x:e.clientX, y:e.clientY }; }
  function applyRect(){ el.style.width = pos.w + 'px'; el.style.height = pos.h + 'px'; el.style.left = pos.x + 'px'; el.style.top = pos.y + 'px'; }

  // build page stack (fallback to DOM if server list is empty)
  let built = false;
  function buildPages(){
    if (built) return;
    if (!pages.length) {
      const fromDom = Array.from(document.querySelectorAll('.page-img')).map(im => im.currentSrc || im.src);
      if (fromDom.length) { console.warn('[popout] READER_PAGES empty; using .page-img elements'); pages = fromDom; }
    }
    const frag = document.createDocumentFragment();
    if (!pages.length) {
      const empty = document.createElement('div');
      empty.style.color = '#aaa';
      empty.style.padding = '1rem';
      empty.textContent = 'No pages in this chapter.';
      frag.appendChild(empty);
    } else {
      pages.forEach((src, i) => {
        const im = document.createElement('img');
        im.src = src;
        im.alt = `page ${i + 1}`;
        im.decoding = 'async';
        im.loading = 'eager';
        im.className = 'popout-page';
        frag.appendChild(im);
      });
    }
    pagesWrap.replaceChildren(frag);
    built = true;
    console.log('[popout] built', pages.length, 'pages');
  }

  function scrollToIndex(i, instant=false){
    if (!pages.length) return;
    i = clamp(i, 0, pages.length - 1);
    const target = pagesWrap.children[i];
    if (!target) return;
    if (instant) scroller.scrollTop = target.offsetTop;
    else scroller.scrollTo({ top: target.offsetTop, behavior: 'smooth' });
  }

  // observe which page is most visible inside the popout
  let io;
  function watchVisibility(){
    if (io) io.disconnect();
    io = new IntersectionObserver(entries => {
      let bestI = idx, bestR = 0;
      for (const e of entries) {
        if (e.intersectionRatio >= bestR) {
          bestR = e.intersectionRatio;
          bestI = Array.prototype.indexOf.call(pagesWrap.children, e.target);
        }
      }
      if (bestR > 0 && bestI !== idx) idx = bestI;
    }, { root: scroller, threshold: Array.from({length:11}, (_,i)=>i/10) });
    Array.from(pagesWrap.children).forEach(img => io.observe(img));
  }

  function show(){
    el.classList.remove('popout-hidden');
    buildPages();
    if (pos.x == null && pos.y == null) {
      const pad = 16;
      pos.w = clamp(pos.w, 260, window.innerWidth - 2*pad);
      pos.h = clamp(pos.h, 180, window.innerHeight - 2*pad);
      pos.x = window.innerWidth - pos.w - pad;
      pos.y = window.innerHeight - pos.h - pad;
      applyRect();
    }
    scrollToIndex(idx, true);
    watchVisibility();
    console.log('[popout] shown');
  }
  function hide(){ el.classList.add('popout-hidden'); if (io) io.disconnect(); console.log('[popout] hidden'); }
  function toggle(){ el.classList.contains('popout-hidden') ? show() : hide(); }

  // drag by header
  header.addEventListener('mousedown', startDrag);
  header.addEventListener('touchstart', startDrag, {passive:false});
  function startDrag(e){
    e.preventDefault();
    const start = getPoint(e);
    const startX = el.offsetLeft;
    const startY = el.offsetTop;
    function move(ev){
      const p = getPoint(ev);
      pos.x = clamp(startX + (p.x - start.x), 8, window.innerWidth - el.offsetWidth - 8);
      pos.y = clamp(startY + (p.y - start.y), 8, window.innerHeight - el.offsetHeight - 8);
      applyRect();
    }
    function up(){ window.removeEventListener('mousemove', move); window.removeEventListener('mouseup', up);
                  window.removeEventListener('touchmove', move); window.removeEventListener('touchend', up); }
    window.addEventListener('mousemove', move);
    window.addEventListener('mouseup', up);
    window.addEventListener('touchmove', move, {passive:false});
    window.addEventListener('touchend', up);
  }

  // custom resize via corner grip
  grip.addEventListener('mousedown', startResize);
  grip.addEventListener('touchstart', startResize, {passive:false});
  function startResize(e){
    e.preventDefault();
    const start = getPoint(e);
    const startW = el.offsetWidth, startH = el.offsetHeight;
    const startX = el.offsetLeft,  startY = el.offsetTop;
    function move(ev){
      const p = getPoint(ev);
      pos.w = clamp(startW + (p.x - start.x), 240, window.innerWidth - startX - 8);
      pos.h = clamp(startH + (p.y - start.y), 160, window.innerHeight - startY - 8);
      applyRect();
    }
    function up(){ window.removeEventListener('mousemove', move); window.removeEventListener('mouseup', up);
                  window.removeEventListener('touchmove', move); window.removeEventListener('touchend', up); }
    window.addEventListener('mousemove', move);
    window.addEventListener('mouseup', up);
    window.addEventListener('touchmove', move, {passive:false});
    window.addEventListener('touchend', up);
  }

  // controls: pop-out toggle and close
  btnToggle.addEventListener('click', toggle);
  btnClose  && btnClose.addEventListener('click', hide);

  // chapter-only navigation on buttons and arrows
  function jumpPrevChapter(){ if (prevChUrl) location.href = prevChUrl; }
  function jumpNextChapter(){ if (nextChUrl) location.href = nextChUrl; }
  btnPrev && btnPrev.addEventListener('click', jumpPrevChapter);
  btnNext && btnNext.addEventListener('click', jumpNextChapter);

  document.addEventListener('keydown', e => {
    const k = e.key.toLowerCase();
    if (k === 'p') { e.preventDefault(); toggle(); }
    if (el.classList.contains('popout-hidden')) return;
    if (k === 'arrowleft')  { e.preventDefault(); jumpPrevChapter(); }
    if (k === 'arrowright') { e.preventDefault(); jumpNextChapter(); }
  });

  // keep popout on-screen on window resize
  window.addEventListener('resize', () => {
    if (el.classList.contains('popout-hidden')) return;
    pos.x = clamp(el.offsetLeft, 8, window.innerWidth  - el.offsetWidth - 8);
    pos.y = clamp(el.offsetTop,  8, window.innerHeight - el.offsetHeight - 8);
    applyRect();
  });

  // optional: keep popout in sync with main scroll when open
  const pageImgs = Array.from(document.querySelectorAll('.page-img'));
  function syncFromMain(){
    if (!pageImgs.length) return;
    let best = 0, bestDist = Infinity;
    const y = window.scrollY + window.innerHeight * 0.35;
    pageImgs.forEach((im, i) => {
      const rect = im.getBoundingClientRect();
      const center = rect.top + window.scrollY + rect.height/2;
      const d = Math.abs(center - y);
      if (d < bestDist) { best = i; bestDist = d; }
    });
    if (best !== idx) { idx = best; if (!el.classList.contains('popout-hidden')) scrollToIndex(idx, true); }
  }
  if (pageImgs.length) {
    window.addEventListener('scroll', () => { if (!el.classList.contains('popout-hidden')) syncFromMain(); }, { passive: true });
  }

  console.log('[popout] ready');
})();
