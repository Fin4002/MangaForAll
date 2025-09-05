
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
