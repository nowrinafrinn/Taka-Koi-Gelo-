/**
 * Bars | Calendar switch on the month view.
 *
 * The page already contains both views (one hidden) and the switch is made
 * of real links, so everything works without JavaScript. This script only
 * makes the switch instant: no reload, no jump to the top of the page. It
 * also updates the address bar and the month navigation, so a refresh,
 * bookmark or "next month" keeps the chosen view.
 */
(function () {
  const card = document.getElementById('daily');
  if (!card) return;

  const switches = card.querySelectorAll('[data-daily]');
  const views = card.querySelectorAll('[data-daily-view]');

  function withMode(url, mode) {
    if (mode === 'calendar') url.searchParams.set('daily', 'calendar');
    else url.searchParams.delete('daily');
    return url;
  }

  function show(mode) {
    views.forEach((view) => { view.hidden = view.dataset.dailyView !== mode; });
    switches.forEach((link) => {
      if (link.dataset.daily === mode) link.setAttribute('aria-current', 'page');
      else link.removeAttribute('aria-current');
    });

    // Address bar: same page, new ?daily value, no new history entry, no scroll.
    const here = withMode(new URL(window.location.href), mode);
    here.hash = '';
    window.history.replaceState(null, '', here);

    // Previous/next month links keep the chosen view.
    document.querySelectorAll('a.period-step').forEach((link) => {
      link.href = withMode(new URL(link.href), mode).toString();
    });

    // The month/year picker keeps it too.
    const form = document.querySelector('form.period-form');
    if (form) {
      let input = form.querySelector('input[name="daily"]');
      if (mode === 'calendar' && !input) {
        input = document.createElement('input');
        input.type = 'hidden';
        input.name = 'daily';
        input.value = 'calendar';
        form.appendChild(input);
      } else if (mode !== 'calendar' && input) {
        input.remove();
      }
    }
  }

  switches.forEach((link) => {
    link.addEventListener('click', (event) => {
      // Let modified clicks (new tab, etc.) behave like normal links.
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) return;
      event.preventDefault();
      show(link.dataset.daily);
    });
  });
})();
