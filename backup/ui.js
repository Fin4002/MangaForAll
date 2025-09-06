
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
