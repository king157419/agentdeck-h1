(function () {
  var root = document.documentElement;
  var btns = Array.prototype.slice.call(document.querySelectorAll('.theme-btn'));

  function mark(t) {
    btns.forEach(function (b) {
      b.classList.toggle('on', b.getAttribute('data-theme') === t);
    });
  }

  function apply(t) {
    root.setAttribute('data-theme', t);
    mark(t);
    try { localStorage.setItem('cxtSiteTheme', t); } catch (e) {}
  }

  btns.forEach(function (b) {
    b.addEventListener('click', function () {
      apply(b.getAttribute('data-theme'));
    });
  });

  mark(root.getAttribute('data-theme') || 'light');

  try {
    var mq = window.matchMedia('(prefers-color-scheme: dark)');
    var onChange = function (e) {
      var saved = null;
      try { saved = localStorage.getItem('cxtSiteTheme'); } catch (err) {}
      if (!saved) {
        var t = e.matches ? 'dark' : 'light';
        root.setAttribute('data-theme', t);
        mark(t);
      }
    };
    if (mq.addEventListener) mq.addEventListener('change', onChange);
    else if (mq.addListener) mq.addListener(onChange);
  } catch (e) {}
})();

(function () {
  function reveal() {
    var id = location.hash.replace('#', '');
    if (!id) return;
    var el = document.getElementById(id);
    if (!el) return;
    if (el.tagName === 'DETAILS') el.open = true;
    if (el.closest) {
      var parent = el.closest('details');
      if (parent) parent.open = true;
    }
    setTimeout(function () {
      el.scrollIntoView({ block: 'start', behavior: 'smooth' });
    }, 60);
  }
  window.addEventListener('hashchange', reveal);
  window.addEventListener('load', reveal);
})();

(function () {
  document.addEventListener('click', function (e) {
    var btn = e.target && e.target.closest ? e.target.closest('.copy-btn') : null;
    if (!btn) return;
    var text = btn.getAttribute('data-copy') || '';

    function done() {
      btn.textContent = '已复制';
      btn.classList.add('done');
      setTimeout(function () {
        btn.textContent = '复制';
        btn.classList.remove('done');
      }, 1800);
    }

    function fallback() {
      var ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      try { if (document.execCommand('copy')) done(); } catch (err) {}
      document.body.removeChild(ta);
    }

    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done).catch(fallback);
    } else {
      fallback();
    }
  });
})();

(function () {
  document.addEventListener('click', function (e) {
    var trigger = e.target && e.target.closest ? e.target.closest('.qr-trigger') : null;
    var wrap = trigger ? trigger.parentElement : null;

    document.querySelectorAll('.qr-pop-wrap.open').forEach(function (w) {
      if (w !== wrap) {
        w.classList.remove('open');
        var t = w.querySelector('.qr-trigger');
        if (t) t.setAttribute('aria-expanded', 'false');
      }
    });

    if (!trigger || !wrap) return;
    var isOpen = wrap.classList.toggle('open');
    trigger.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
  });
})();

(function () {
  var bar = document.getElementById('filters');
  var list = document.getElementById('res-list');
  if (!bar || !list) return;

  var state = {model: 'all', type: 'all'};
  var items = Array.prototype.slice.call(list.querySelectorAll('.res-item'));
  var groups = Array.prototype.slice.call(list.querySelectorAll('.res-group'));
  var empty = document.getElementById('res-empty');

  function apply() {
    var visible = 0;
    items.forEach(function (el) {
      var ok = (state.model === 'all' || el.getAttribute('data-model') === state.model)
        && (state.type === 'all' || el.getAttribute('data-type') === state.type);
      el.style.display = ok ? '' : 'none';
      if (ok) visible += 1;
    });
    groups.forEach(function (group) {
      var model = group.getAttribute('data-model');
      var any = items.some(function (el) {
        return el.getAttribute('data-model') === model && el.style.display !== 'none';
      });
      group.style.display = any ? '' : 'none';
    });
    if (empty) empty.style.display = visible ? 'none' : '';
  }

  bar.addEventListener('click', function (e) {
    var btn = e.target && e.target.closest ? e.target.closest('.chip-btn') : null;
    if (!btn) return;
    var group = btn.getAttribute('data-filter');
    state[group] = btn.getAttribute('data-value');
    bar.querySelectorAll('.chip-btn[data-filter="' + group + '"]').forEach(function (item) {
      item.classList.toggle('on', item === btn);
    });
    apply();
  });
})();

(function () {
  var nav = document.querySelector('.anchor-nav');
  if (!nav) return;

  var links = Array.prototype.slice.call(nav.querySelectorAll('a'));
  var sections = links.map(function (link) {
    return document.getElementById(link.getAttribute('href').slice(1));
  });

  function sync() {
    var active = 0;
    sections.forEach(function (section, index) {
      if (section && section.getBoundingClientRect().top <= 150) active = index;
    });
    links.forEach(function (link, index) {
      link.classList.toggle('on', index === active);
    });
  }

  window.addEventListener('scroll', sync, {passive: true});
  sync();
})();

(function () {
  var tabs = Array.prototype.slice.call(document.querySelectorAll('.fr-tab'));
  var panels = Array.prototype.slice.call(document.querySelectorAll('[data-fr-panel]'));
  if (!tabs.length || !panels.length) return;

  function show(name) {
    tabs.forEach(function (tab) {
      var on = tab.getAttribute('data-fr') === name;
      tab.classList.toggle('on', on);
      tab.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
    panels.forEach(function (panel) {
      panel.hidden = panel.getAttribute('data-fr-panel') !== name;
    });
  }

  tabs.forEach(function (tab) {
    tab.addEventListener('click', function () { show(tab.getAttribute('data-fr')); });
  });

  Array.prototype.slice.call(document.querySelectorAll('[data-fr-tab]')).forEach(function (link) {
    link.addEventListener('click', function () { show(link.getAttribute('data-fr-tab')); });
  });
})();
