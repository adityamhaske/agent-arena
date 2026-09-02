/* Agent Arena docs — progressive enhancement only.
 *
 * Every page is fully readable with this file blocked: the theme falls back to
 * the OS preference, the sidebar is visible on desktop, and code blocks are
 * selectable by hand. Nothing here is load-bearing.
 */

'use strict';

/* ------------------------------------------------------------ theme */

(function theme() {
  var root = document.documentElement;

  function current() {
    var explicit = root.getAttribute('data-theme');
    if (explicit) return explicit;
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }

  document.querySelectorAll('[data-theme-toggle]').forEach(function (button) {
    button.addEventListener('click', function () {
      var next = current() === 'dark' ? 'light' : 'dark';
      root.setAttribute('data-theme', next);
      try { localStorage.setItem('aa-theme', next); } catch (e) {}
      button.setAttribute('aria-label', 'Switch to ' + (next === 'dark' ? 'light' : 'dark') + ' theme');
    });
  });
})();

/* -------------------------------------------------------- mobile nav */

(function mobileNav() {
  var toggle = document.querySelector('[data-nav-toggle]');
  var sidebar = document.getElementById('sidebar');
  if (!toggle || !sidebar) return;

  toggle.addEventListener('click', function () {
    var open = sidebar.classList.toggle('open');
    toggle.setAttribute('aria-expanded', String(open));
  });

  // Following a link should close the drawer, not leave it covering the page.
  sidebar.addEventListener('click', function (event) {
    if (event.target.closest('a')) {
      sidebar.classList.remove('open');
      toggle.setAttribute('aria-expanded', 'false');
    }
  });
})();

/* ------------------------------------------------- copy to clipboard */

(function copyButtons() {
  function copy(text, button) {
    var done = function () {
      var original = button.textContent;
      button.textContent = 'Copied';
      button.classList.add('done');
      setTimeout(function () {
        button.textContent = original;
        button.classList.remove('done');
      }, 1600);
    };
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(done, function () {});
      return;
    }
    // http:// or an older browser — the textarea fallback still works.
    var scratch = document.createElement('textarea');
    scratch.value = text;
    scratch.setAttribute('readonly', '');
    scratch.style.position = 'absolute';
    scratch.style.left = '-9999px';
    document.body.appendChild(scratch);
    scratch.select();
    try { document.execCommand('copy'); done(); } catch (e) {}
    document.body.removeChild(scratch);
  }

  document.querySelectorAll('[data-copy]').forEach(function (button) {
    button.addEventListener('click', function () {
      var target = document.querySelector(button.getAttribute('data-copy'));
      if (target) copy(target.textContent.trim(), button);
    });
  });

  // Add a copy button to every code block that does not already have one.
  document.querySelectorAll('.md pre, .code-wrap > pre').forEach(function (pre) {
    var wrap = pre.parentElement;
    if (!wrap.classList.contains('code-wrap')) {
      wrap = document.createElement('div');
      wrap.className = 'code-wrap';
      pre.parentNode.insertBefore(wrap, pre);
      wrap.appendChild(pre);
    }
    if (wrap.querySelector(':scope > .copy')) return;
    var button = document.createElement('button');
    button.type = 'button';
    button.className = 'copy';
    button.textContent = 'Copy';
    button.setAttribute('aria-label', 'Copy code to clipboard');
    button.addEventListener('click', function () { copy(pre.innerText, button); });
    wrap.appendChild(button);
  });
})();

/* ----------------------------------------------------- wide tables */

(function scrollableTables() {
  // Markdown tables can be wider than the column; let them scroll rather than
  // pushing the whole page sideways.
  document.querySelectorAll('.md > table').forEach(function (table) {
    var wrap = document.createElement('div');
    wrap.className = 'table-scroll';
    table.parentNode.insertBefore(wrap, table);
    wrap.appendChild(table);
  });
})();

/* --------------------------------------------------- table of contents */

(function scrollspy() {
  var links = Array.prototype.slice.call(document.querySelectorAll('.toc-col a[href^="#"]'));
  if (!links.length || !('IntersectionObserver' in window)) return;

  var byId = {};
  var targets = [];
  links.forEach(function (link) {
    var id = decodeURIComponent(link.getAttribute('href').slice(1));
    var heading = document.getElementById(id);
    if (heading) { byId[id] = link; targets.push(heading); }
  });

  var visible = new Set();
  var observer = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
      if (entry.isIntersecting) visible.add(entry.target.id);
      else visible.delete(entry.target.id);
    });
    var first = targets.find(function (h) { return visible.has(h.id); });
    links.forEach(function (link) { link.classList.remove('active'); });
    if (first && byId[first.id]) byId[first.id].classList.add('active');
  }, { rootMargin: '-72px 0px -70% 0px' });

  targets.forEach(function (heading) { observer.observe(heading); });
})();
