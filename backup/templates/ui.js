
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
