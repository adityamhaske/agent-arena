/* Agent Arena UI — vanilla JS, no build step, no dependencies.
 *
 * Design rule for everything below: a person who has never heard of a
 * "composite score" must be able to start an evaluation, read the result, and
 * know what to do next. Every number on screen is paired with a sentence, and
 * the sentences come from the server (agent_arena/web/language.py) so the UI
 * and the CLI can never tell different stories.
 */

'use strict';

const state = {
  catalog: null,
  projects: [],
  project: null,
  result: null,
  job: null,
  poll: null,
  draft: null,
};

/* ---------------------------------------------------------------- utils */

const $ = (sel, root = document) => root.querySelector(sel);
const app = () => $('#app');

/** Escape before interpolation. Every dynamic value on this page goes through here. */
function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

function toast(message, isError = false) {
  const el = $('#toast');
  el.textContent = message;
  el.className = 'toast' + (isError ? ' bad' : '');
  el.hidden = false;
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => { el.hidden = true; }, isError ? 6000 : 3000);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  let payload = {};
  try { payload = await response.json(); } catch { /* non-JSON error page */ }
  if (!response.ok) {
    const error = new Error(payload.error || `Request failed (${response.status})`);
    error.detail = payload.detail;
    throw error;
  }
  return payload;
}

const pct = (n) => (n == null ? '—' : `${Math.round(n * 100)}%`);
const fixed = (n, d = 3) => (n == null ? '—' : Number(n).toFixed(d));

function timeAgo(iso) {
  if (!iso) return 'never';
  const then = new Date(iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z');
  const seconds = (Date.now() - then.getTime()) / 1000;
  if (Number.isNaN(seconds)) return iso;
  if (seconds < 90) return 'just now';
  if (seconds < 5400) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 172800) return `${Math.round(seconds / 3600)} hours ago`;
  return `${Math.round(seconds / 86400)} days ago`;
}

function formatTime(iso) {
  if (!iso) return '';
  const d = new Date(iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z');
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function formatDate(iso) {
  if (!iso) return 'Undated';
  const d = new Date(iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z');
  if (Number.isNaN(d.getTime())) return 'Undated';
  const now = new Date();
  const isToday = d.toDateString() === now.toDateString();
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  const isYesterday = d.toDateString() === yesterday.toDateString();
  if (isToday) return 'Today · ' + d.toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' });
  if (isYesterday) return 'Yesterday · ' + d.toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' });
  return d.toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' });
}

function groupRunsByDate(runs) {
  const groups = new Map();
  for (const r of runs) {
    const key = r.started_at ? formatDate(r.started_at) : 'Undated';
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(r);
  }
  return Array.from(groups.entries()).map(([date, items]) => ({ date, runs: items }));
}

function bindDropdowns() {
  // Global click-outside listener is registered once on document
}

// Global click-outside listener for interactive dropdowns
document.addEventListener('click', (e) => {
  const toggle = e.target.closest('[data-dropdown-toggle]');
  if (toggle) {
    e.preventDefault();
    e.stopPropagation();
    const dropdown = toggle.closest('.dropdown');
    const wasOpen = dropdown?.classList.contains('open');
    document.querySelectorAll('.dropdown.open').forEach((d) => d.classList.remove('open'));
    if (!wasOpen && dropdown) {
      dropdown.classList.add('open');
    }
    return;
  }
  if (!e.target.closest('.dropdown')) {
    document.querySelectorAll('.dropdown.open').forEach((d) => d.classList.remove('open'));
  }
});

/** Mirrors language.explain_weights for live slider feedback only. The
 *  sentence shown on a results page always comes from the server. */
function weightSentence(weights) {
  const labels = state.catalog?.metric_language || {};
  const total = Object.values(weights).reduce((a, b) => a + b, 0);
  const parts = Object.entries(weights)
    .filter(([, w]) => w > 0)
    .sort((a, b) => b[1] - a[1])
    .map(([name, w]) => `${(labels[name]?.slider || name).toLowerCase()} (${Math.round((w / total) * 100)}%)`);
  if (!parts.length) return 'Move at least one slider above zero.';
  if (parts.length === 1) return `You care only about ${parts[0]}.`;
  return `You care most about ${parts[0]}, then ${parts.slice(1).join(', then ')}.`;
}

/* --------------------------------------------------------------- router */

const routes = [
  [/^\/?$/, viewOverview],
  [/^\/projects$/, viewProjects],
  [/^\/new$/, viewWizard],
  [/^\/runs$/, viewAllRuns],
  [/^\/models$/, viewModels],
  [/^\/providers$/, viewProviders],
  [/^\/scorers$/, viewScorers],
  [/^\/settings$/, () => viewSettings('general')],
  [/^\/settings\/([a-z-]+)$/, viewSettings],
  [/^\/p\/([a-z0-9_-]+)$/, viewProject],
  [/^\/p\/([a-z0-9_-]+)\/run$/, viewRun],
  [/^\/p\/([a-z0-9_-]+)\/results$/, viewResults],
  [/^\/p\/([a-z0-9_-]+)\/priorities$/, viewPriorities],
  [/^\/p\/([a-z0-9_-]+)\/examples$/, viewExamples],
  [/^\/p\/([a-z0-9_-]+)\/history$/, viewHistory],
  [/^\/p\/([a-z0-9_-]+)\/cases\/([^/]+)$/, viewRunCases],
];

/* Icons are inline SVG rather than a font or a sprite sheet: no network, no
 * build step, and they inherit currentColor so they work in both themes
 * without a second asset. 16px on a 24 grid, 2px stroke, round caps — one
 * geometry for the whole set so they sit together. */
const ICONS = {
  overview:  'M3 12h6v9H3zM10.5 3h3v18h-3zM15 8h6v13h-6z',
  projects:  'M4 5h7l2 2h7v12H4zM4 10h16',
  runs:      'M4 7h16M4 12h16M4 17h10',
  models:    'M12 3l8 4.5v9L12 21l-8-4.5v-9zM12 12l8-4.5M12 12v9M12 12L4 7.5',
  scorers:   'M20 6L9 17l-5-5',
  providers: 'M4 8h11l-3-3M20 16H9l3 3',
  settings:  'M12 15a3 3 0 100-6 3 3 0 000 6zM19.4 15a1.7 1.7 0 00.3 1.9l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.7 1.7 0 00-2.9 1.2v.2a2 2 0 11-4 0v-.1a1.7 1.7 0 00-1.1-1.6 1.7 1.7 0 00-1.9.4l-.1.1a2 2 0 11-2.8-2.8l.1-.1a1.7 1.7 0 00-1.2-2.9h-.2a2 2 0 110-4h.1a1.7 1.7 0 001.6-1.1 1.7 1.7 0 00-.4-1.9l-.1-.1a2 2 0 112.8-2.8l.1.1a1.7 1.7 0 001.9.3h.1A1.7 1.7 0 0010 3.5v-.2a2 2 0 114 0v.1a1.7 1.7 0 001 1.6 1.7 1.7 0 001.9-.4l.1-.1a2 2 0 112.8 2.8l-.1.1a1.7 1.7 0 00-.3 1.9v.1a1.7 1.7 0 001.6 1H21a2 2 0 110 4h-.1a1.7 1.7 0 00-1.5 1z',
  menu:      'M4 7h16M4 12h16M4 17h16',
  sun:       'M12 17a5 5 0 100-10 5 5 0 000 10zM12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4',
  moon:      'M21 12.8A9 9 0 1111.2 3a7 7 0 009.8 9.8z',
  play:      'M6 4l14 8-14 8z',
  refresh:   'M21 12a9 9 0 11-2.6-6.4M21 3v6h-6',
  plug:      'M9 3v6M15 3v6M6 9h12v3a6 6 0 01-12 0zM12 18v3',
  trash:     'M4 7h16M9 7V5h6v2M6 7l1 13h10l1-13',
  edit:      'M4 20h4L20 8l-4-4L4 16z',
  external:  'M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 01-1 1H6a1 1 0 01-1-1V8a1 1 0 011-1h5',
  check:     'M20 6L9 17l-5-5',
  x:         'M6 6l12 12M18 6L6 18',
};

/** An inline SVG icon. `title` becomes a tooltip — the explanation that lets
 *  an icon replace a word rather than just hide one. */
function icon(name, { size = 16, title = '' } = {}) {
  const path = ICONS[name];
  if (!path) return '';
  return `<svg viewBox="0 0 24 24" width="${size}" height="${size}" fill="none"
    stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
    ${title ? 'role="img"' : 'aria-hidden="true"'}>${title ? `<title>${esc(title)}</title>` : ''}
    <path d="${path}"/></svg>`;
}

/** A status dot. The colour is the signal, the title is the reason. */
function dot(kind, title) {
  return `<span class="dot ${kind}" title="${esc(title)}" role="img" aria-label="${esc(title)}"></span>`;
}

/* The sidenav. `match` decides which entry is highlighted for a given hash —
 * a prefix test rather than equality, so /p/foo/results still lights up
 * "Projects" instead of leaving the user with no sense of where they are. */
const NAV = [
  { group: 'Evaluate' },
  { href: '#/', icon: 'overview', label: 'Overview', match: (p) => p === '/' },
  { href: '#/projects', icon: 'projects', label: 'Projects', match: (p) => p === '/projects' || p.startsWith('/p/') },
  { href: '#/runs', icon: 'runs', label: 'Runs', match: (p) => p === '/runs' },
  { group: 'Reference' },
  { href: '#/models', icon: 'models', label: 'Models', match: (p) => p === '/models' },
  { href: '#/scorers', icon: 'scorers', label: 'Scorers', match: (p) => p === '/scorers' },
  { href: '#/providers', icon: 'providers', label: 'Providers', match: (p) => p === '/providers' },
];

/* Settings sits at the bottom of the rail, away from the things you use while
 * actually working — it is configuration, not a destination you pass through. */
const NAV_FOOT = [
  { href: '#/settings', icon: 'settings', label: 'Settings', match: (p) => p.startsWith('/settings') },
];

function navLink(item, path) {
  return `<a href="${item.href}" data-link class="${item.match(path) ? 'on' : ''}">
    <span class="ico">${icon(item.icon)}</span>${esc(item.label)}</a>`;
}

function renderNav(path) {
  $('#nav').innerHTML = NAV.map((item) => (
    item.group ? `<p class="nav-group">${esc(item.group)}</p>` : navLink(item, path)
  )).join('');
  $('#nav-foot-links').innerHTML = NAV_FOOT.map((item) => navLink(item, path)).join('');
}

function crumbs(...parts) {
  const el = $('#crumbs');
  if (!el) return;
  el.innerHTML = parts.map((part, i) => {
    const last = i === parts.length - 1;
    const node = part.href && !last
      ? `<a href="${part.href}" data-link>${esc(part.label)}</a>`
      : `<span class="${last ? 'here' : ''}">${esc(part.label)}</span>`;
    return i ? `<span class="sep">/</span>${node}` : node;
  }).join('');
}

async function router() {
  if (state.poll) { clearInterval(state.poll); state.poll = null; }
  // The hash carries a query string on links like `#/p/x/results?run=<id>`.
  // Route patterns are anchored, so it has to come off the path before
  // matching or every such link falls through to the `#/` fallback below.
  const raw = location.hash.replace(/^#/, '') || '/';
  const cut = raw.indexOf('?');
  const path = cut === -1 ? raw : raw.slice(0, cut) || '/';
  const params = new URLSearchParams(cut === -1 ? '' : raw.slice(cut + 1));
  renderNav(path);
  $('#sidenav').classList.remove('open');
  $('#nav-toggle').setAttribute('aria-expanded', 'false');
  for (const [pattern, view] of routes) {
    const match = path.match(pattern);
    if (match) {
      app().innerHTML = '<div class="loading">Loading…</div>';
      try {
        await view(...match.slice(1), params);
      } catch (error) {
        renderError(error);
      }
      window.scrollTo(0, 0);
      return;
    }
  }
  location.hash = '#/';
}

function renderError(error) {
  app().innerHTML = `
    <div class="card">
      <h2>That did not work</h2>
      <p>${esc(error.message)}</p>
      ${error.detail ? `<details><summary>Technical detail</summary><pre>${esc(error.detail)}</pre></details>` : ''}
      <p class="btn-row"><a class="btn" href="#/" data-link>Back to your evaluations</a></p>
    </div>`;
}

/* ----------------------------------------------------------- view: home */

async function viewHome() {
  const { projects } = await api('/api/projects');
  state.projects = projects;

  const cards = projects.map((p) => `
    <a class="project-card" href="#/p/${esc(p.name)}" data-link>
      <h3>${esc(p.project || p.name)}</h3>
      <p class="small muted mb0">${esc(p.description || 'No description yet.')}</p>
      <div class="meta">
        ${p.models} model${p.models === 1 ? '' : 's'} · ${p.tests} example${p.tests === 1 ? '' : 's'}
        · last run ${esc(timeAgo(p.last_run?.started_at))}
        ${p.last_run?.winner ? `· winner <strong>${esc(p.last_run.winner)}</strong>` : ''}
      </div>
    </a>`).join('');

  app().innerHTML = `
    <div class="page-head">
      <h1>Your evaluations</h1>
      <p class="lede">
        Each evaluation answers one question: <em>for this job, which AI model should we
        actually use?</em> You give it examples and say what matters to you — accuracy,
        cost, speed — and it tells you which model wins and what that choice costs.
      </p>
    </div>
    ${projects.length ? `<div class="grid">${cards}</div>` : `
      <div class="empty">
        <h2>Nothing here yet</h2>
        <p>Set up your first evaluation — it takes about five minutes,<br>and you can run it
        for free against simulated models before spending anything.</p>
        <p><a class="btn btn-primary btn-lg" href="#/new" data-link>Start an evaluation</a></p>
      </div>`}`;
}

/* --------------------------------------------------------- view: wizard */

const WIZARD_STEPS = ['What is the job?', 'Name it', 'Which models?', 'What matters?', 'Your examples'];

async function viewWizard() {
  if (!state.catalog) state.catalog = await api('/api/catalog');
  if (!state.draft) {
    state.draft = {
      step: 0,
      preset: null,
      name: '',
      description: '',
      labels: ['', ''],
      models: state.catalog.demo_models.slice(0, 3).map((m) => m.key),
      weights: { accuracy: 0.55, cost: 0.25, latency: 0.20 },
      budget: '',
      latencyTarget: '',
      minAccuracy: '',
      trials: 3,
      tests: [{ input: '', reference: '' }, { input: '', reference: '' }, { input: '', reference: '' }],
    };
  }
  renderWizard();
}

function renderWizard() {
  const d = state.draft;
  const steps = WIZARD_STEPS.map((label, i) => `
    <div class="step" data-state="${i === d.step ? 'current' : i < d.step ? 'done' : 'todo'}">
      <span class="step-num">${i < d.step ? '✓' : i + 1}</span>${esc(label)}
    </div>`).join('');

  app().innerHTML = `
    <div class="page-head">
      <div>
        <div class="eyebrow">New evaluation</div>
        <h1>${esc(WIZARD_STEPS[d.step])}</h1>
      </div>
    </div>
    <div class="steps">${steps}</div>
    <div class="card" id="wizard-body">${wizardStep()}</div>
    <div class="btn-row">
      ${d.step > 0 ? '<button class="btn" data-act="back">Back</button>' : '<a class="btn" href="#/" data-link>Cancel</a>'}
      <span class="spacer"></span>
      ${d.step < WIZARD_STEPS.length - 1
        ? '<button class="btn btn-primary" data-act="next">Continue</button>'
        : '<button class="btn btn-primary btn-lg" data-act="create">Create evaluation</button>'}
    </div>`;

  if (d.step === 2) {
    const searchInput = document.getElementById('wizard-model-search');
    const chipContainer = document.getElementById('wizard-filter-chips');
    const choicesContainer = document.getElementById('wizard-body');

    function applyWizardFilter() {
      if (!choicesContainer) return;
      const query = (searchInput?.value || '').trim().toLowerCase();
      const activeChip = chipContainer?.querySelector('.filter-chip.active');
      const activeFilter = activeChip?.getAttribute('data-wizard-filter') || 'all';

      const buttons = choicesContainer.querySelectorAll('button.choice[data-filter-name]');
      buttons.forEach((btn) => {
        const name = (btn.getAttribute('data-filter-name') || '').toLowerCase();
        const isDemo = btn.getAttribute('data-is-demo') === 'true';
        const isAvailable = btn.getAttribute('data-available') === 'true';
        const provider = (btn.getAttribute('data-provider') || '').toLowerCase();

        let matchesFilter = true;
        if (activeFilter === 'ready') matchesFilter = isAvailable || isDemo;
        else if (activeFilter === 'demo') matchesFilter = isDemo;
        else if (activeFilter !== 'all') matchesFilter = provider.includes(activeFilter);

        const matchesSearch = !query || name.includes(query) || provider.includes(query);
        btn.style.display = (matchesFilter && matchesSearch) ? '' : 'none';
      });

      choicesContainer.querySelectorAll('.wizard-model-section').forEach((sec) => {
        const visibleBtns = sec.querySelectorAll('button.choice:not([style*="display: none"])');
        sec.style.display = visibleBtns.length ? '' : 'none';
      });
    }

    if (chipContainer) {
      chipContainer.addEventListener('click', (e) => {
        const btn = e.target.closest('.filter-chip');
        if (!btn) return;
        chipContainer.querySelectorAll('.filter-chip').forEach((c) => c.classList.remove('active'));
        btn.classList.add('active');
        applyWizardFilter();
      });
    }

    if (searchInput) {
      searchInput.addEventListener('input', applyWizardFilter);
    }
  }
}

function wizardStep() {
  const d = state.draft;
  const preset = state.catalog.presets.find((p) => p.id === d.preset);

  if (d.step === 0) {
    return `
      <p class="hint">Pick the closest match. This sets how answers get marked right or wrong —
      you can change it later.</p>
      <div class="choices">
        ${state.catalog.presets.map((p) => `
          <button class="choice" data-preset="${esc(p.id)}" aria-pressed="${d.preset === p.id}">
            <strong>${esc(p.title)}</strong>
            <span>${esc(p.blurb)}</span>
            <em>e.g. ${esc(p.example)}</em>
          </button>`).join('')}
      </div>`;
  }

  if (d.step === 1) {
    return `
      <div class="field">
        <label for="w-name">What should we call this?</label>
        <p class="hint">Letters, numbers, dashes. This becomes the folder name.</p>
        <input id="w-name" type="text" value="${esc(d.name)}" placeholder="support-triage" data-bind="name">
      </div>
      <div class="field">
        <label for="w-desc">What is it for? <span class="muted small">(optional)</span></label>
        <textarea id="w-desc" data-bind="description" placeholder="Route inbound support tickets to the right queue.">${esc(d.description)}</textarea>
      </div>
      ${preset?.needs_labels ? `
        <div class="field">
          <label>What are the categories?</label>
          <p class="hint">Every answer has to be exactly one of these. At least two.</p>
          <div id="labels">
            ${d.labels.map((label, i) => `
              <div class="btn-row" style="margin-bottom:.4rem">
                <input type="text" value="${esc(label)}" data-label="${i}" placeholder="billing">
                <button class="btn btn-sm" data-act="drop-label" data-i="${i}" aria-label="Remove category">✕</button>
              </div>`).join('')}
          </div>
          <button class="btn btn-sm" data-act="add-label">Add a category</button>
        </div>` : ''}
      ${preset?.caution ? `<div class="callout warn"><p class="mb0 small">${esc(preset.caution)}</p></div>` : ''}`;
  }

  if (d.step === 2) {
    const rawDemo = state.catalog.demo_models || [];
    const rawReal = state.catalog.real_models || [];

    // Sort demo models best accuracy first
    const demo = [...rawDemo].sort((a, b) => (b.params?.accuracy ?? 0) - (a.params?.accuracy ?? 0));

    // Sort real models: ready first, best capability tier first
    const real = [...rawReal].sort((a, b) => {
      const aAvail = a.available ? 1 : 0;
      const bAvail = b.available ? 1 : 0;
      if (bAvail !== aAvail) return bAvail - aAvail;
      const aTier = getModelTierInfo(a).tier;
      const bTier = getModelTierInfo(b).tier;
      if (bTier !== aTier) return bTier - aTier;
      const aOut = Number(a.output_usd_per_mtok) || 0;
      const bOut = Number(b.output_usd_per_mtok) || 0;
      if (bOut !== aOut) return bOut - aOut;
      return (a.model || '').localeCompare(b.model || '');
    });

    const readyReal = real.filter((m) => m.available);
    const unavailableReal = real.filter((m) => !m.available);

    const renderCard = (m, isDemo = false) => {
      const key = isDemo ? m.key : m.model;
      const isSelected = d.models.includes(key);
      if (isDemo) {
        return `
          <button class="choice" data-model="${esc(key)}" data-filter-name="${esc(m.key)} ${esc(m.label || '')} ${esc(m.model)}" data-is-demo="true" data-available="true" data-provider="mock" aria-pressed="${isSelected}">
            <div class="choice-header">
              <strong><span class="dot ok" title="Ready to use"></span> ${esc(m.label)}</strong>
              <span class="pill pill-sm ok">${m.params?.accuracy != null ? m.params.accuracy + '%' : 'Free'}</span>
            </div>
            <span>${esc(m.blurb || '')} · ${m.params?.latency_ms ? m.params.latency_ms + 'ms' : 'Instant'}</span>
            <em class="good"><span class="dot ok"></span> Ready to evaluate (Free)</em>
          </button>`;
      }
      const tier = getModelTierInfo(m);
      if (m.available) {
        return `
          <button class="choice" data-model="${esc(key)}" data-filter-name="${esc(m.model)} ${esc(m.display || '')} ${esc(m.provider || '')}" data-is-demo="false" data-available="true" data-provider="${esc(m.provider || '')}" aria-pressed="${isSelected}">
            <div class="choice-header">
              <strong><span class="dot ok" title="Ready to use"></span> ${esc(m.display || m.model)}</strong>
              <span class="model-tier-pill ${tier.cls}">${tier.label}</span>
            </div>
            <span>${esc(m.provider)} · $${esc(m.input_usd_per_mtok ?? '?')} in / $${esc(m.output_usd_per_mtok ?? '?')} out per Mtok</span>
            <em class="good"><span class="dot ok"></span> Ready to use</em>
          </button>`;
      } else {
        return `
          <button class="choice is-disabled" data-model="${esc(key)}" data-filter-name="${esc(m.model)} ${esc(m.display || '')} ${esc(m.provider || '')}" data-is-demo="false" data-available="false" data-provider="${esc(m.provider || '')}" aria-pressed="${isSelected}"
                  disabled title="Set ${esc(m.api_key_env || 'API key')} in your environment to unlock">
            <div class="choice-header">
              <strong><span class="dot warn" title="Requires API key"></span> ${esc(m.display || m.model)}</strong>
              <span class="model-tier-pill ${tier.cls}">${tier.label}</span>
            </div>
            <span>${esc(m.provider)} · $${esc(m.input_usd_per_mtok ?? '?')} in / $${esc(m.output_usd_per_mtok ?? '?')} out per Mtok</span>
            <em class="warn"><span class="dot warn"></span> Needs ${esc(m.api_key_env || 'API key')} — not set</em>
          </button>`;
      }
    };

    return `
      <div class="model-toolbar" style="margin-bottom:1.5rem;">
        <div class="model-filter-chips" id="wizard-filter-chips">
          <button type="button" class="filter-chip active" data-wizard-filter="all">All (${demo.length + real.length})</button>
          <button type="button" class="filter-chip" data-wizard-filter="ready"><span class="dot ok" style="width:7px;height:7px;margin-right:4px;"></span>Ready (${demo.length + readyReal.length})</button>
          <button type="button" class="filter-chip" data-wizard-filter="demo">Simulated (${demo.length})</button>
          <button type="button" class="filter-chip" data-wizard-filter="anthropic">Anthropic</button>
          <button type="button" class="filter-chip" data-wizard-filter="openai">OpenAI</button>
          <button type="button" class="filter-chip" data-wizard-filter="gemini">Gemini</button>
          <button type="button" class="filter-chip" data-wizard-filter="mistral">Mistral</button>
        </div>
        <div class="model-search-box">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="opacity:.6"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
          <input type="search" id="wizard-model-search" placeholder="Filter models by name..." autocomplete="off">
        </div>
      </div>

      <div class="wizard-model-section" data-section="ready">
        <h3><span class="dot ok"></span> Available & Ready Models (${demo.length + readyReal.length})</h3>
        <p class="hint">Active models ready to evaluate right now — zero configuration required.</p>
        <div class="choices">
          ${demo.map((m) => renderCard(m, true)).join('')}
          ${readyReal.map((m) => renderCard(m, false)).join('')}
        </div>
      </div>

      <div class="wizard-model-section" data-section="unavailable" style="margin-top:2rem;">
        <h3><span class="dot warn"></span> Requires API Key (${unavailableReal.length})</h3>
        <p class="hint">These models make real API calls and need their corresponding environment variable key configured on this machine.</p>
        <div class="choices">
          ${unavailableReal.map((m) => renderCard(m, false)).join('')}
        </div>
      </div>`;
  }

  if (d.step === 3) {
    return `
      <p class="hint">Drag each slider to say how much it matters. There is no right answer —
      a chatbot people wait on and a background job have very different priorities.</p>
      ${['accuracy', 'cost', 'latency'].map((metric) => {
        const meta = state.catalog.metric_language[metric] || {};
        return `
          <div class="weight">
            <div class="weight-label">${esc(meta.slider || metric)}<small>${esc(meta.question || '')}</small></div>
            <div class="weight-value" data-out="${metric}">${Math.round(d.weights[metric] * 100)}</div>
            <input type="range" min="0" max="100" step="5" value="${Math.round(d.weights[metric] * 100)}" data-weight="${metric}">
          </div>`;
      }).join('')}
      <div class="callout" id="weights-sentence"><p class="mb0">${esc(weightSentence(d.weights))}</p></div>

      <h3 style="margin-top:1.5rem">Hard limits <span class="muted small">(optional)</span></h3>
      <p class="hint">A model that breaks one of these is ruled out completely rather than just
      ranked lower — a leaderboard that recommends something you cannot ship is useless.</p>
      <div class="field-row">
        <div class="field">
          <label for="w-acc">Minimum accuracy</label>
          <p class="hint">Out of 100. Leave blank for no floor.</p>
          <input id="w-acc" type="number" min="0" max="100" step="1" value="${esc(d.minAccuracy)}" data-bind="minAccuracy" placeholder="70">
        </div>
        <div class="field">
          <label for="w-budget">Budget per 1,000 uses</label>
          <p class="hint">In dollars. Used to score cost, not to cap it.</p>
          <input id="w-budget" type="number" min="0" step="0.01" value="${esc(d.budget)}" data-bind="budget" placeholder="2.00">
        </div>
      </div>
      <div class="field-row">
        <div class="field">
          <label for="w-latency">Target answer time</label>
          <p class="hint">In milliseconds. 1000 = one second.</p>
          <input id="w-latency" type="number" min="0" step="50" value="${esc(d.latencyTarget)}" data-bind="latencyTarget" placeholder="800">
        </div>
        <div class="field">
          <label for="w-trials">Repeats per example</label>
          <p class="hint">Models are not perfectly consistent. Three runs of each example
          separates a real difference from luck.</p>
          <input id="w-trials" type="number" min="1" max="20" value="${esc(d.trials)}" data-bind="trials">
        </div>
      </div>`;
  }

  // step 4 — examples
  const answerLabel = preset?.answer_label || 'Correct answer';
  return `
    <p class="hint">Each row is one real case with the answer you would accept. Five to twenty
    covers most jobs. Weak examples give you a confident wrong recommendation, so use real ones.</p>
    <div class="table-wrap">
      <table>
        <thead><tr>
          <th style="width:52%">What goes in</th>
          <th style="width:40%">${esc(answerLabel)}</th>
          <th></th>
        </tr></thead>
        <tbody id="tests-body">
          ${state.draft.tests.map((t, i) => `
            <tr>
              <td><textarea data-test="${i}" data-key="input" placeholder="${esc(preset?.input_hint || 'One real case, exactly as it would arrive.')}">${esc(t.input)}</textarea></td>
              <td><textarea data-test="${i}" data-key="reference" placeholder="${esc(preset?.answer_hint || '')}">${esc(t.reference)}</textarea></td>
              <td><button class="btn btn-sm" data-act="drop-test" data-i="${i}" aria-label="Remove example">✕</button></td>
            </tr>`).join('')}
        </tbody>
      </table>
    </div>
    <div class="btn-row" style="margin-top:.8rem">
      <button class="btn btn-sm" data-act="add-test">Add an example</button>
      <button class="btn btn-sm" data-act="paste-tests">Paste a list</button>
      ${preset?.starter?.length
        ? `<button class="btn btn-sm" data-act="fill-example">Show me one</button>`
        : ''}
    </div>`;
}

function wizardValidate() {
  const d = state.draft;
  if (d.step === 0 && !d.preset) return 'Pick what kind of job this is.';
  if (d.step === 1) {
    if (!d.name.trim()) return 'Give this evaluation a name.';
    const preset = state.catalog.presets.find((p) => p.id === d.preset);
    if (preset?.needs_labels && d.labels.filter((l) => l.trim()).length < 2) {
      return 'Sorting needs at least two categories.';
    }
  }
  if (d.step === 2 && !d.models.length) return 'Pick at least one model to compare.';
  if (d.step === 3 && Object.values(d.weights).every((w) => w <= 0)) {
    return 'At least one thing has to matter — move a slider above zero.';
  }
  if (d.step === 4 && !d.tests.some((t) => t.input.trim())) return 'Add at least one example.';
  return null;
}

async function wizardCreate() {
  const d = state.draft;
  const problem = wizardValidate();
  if (problem) { toast(problem, true); return; }

  const chosen = d.models.map((key) => {
    const demo = state.catalog.demo_models.find((m) => m.key === key);
    if (demo) return { key: demo.key, model: demo.model, label: demo.label, params: demo.params, card: demo.card };
    const real = state.catalog.real_models.find((m) => m.model === key);
    return { key: key.replace(/[^a-z0-9_-]+/gi, '_').toLowerCase(), model: key, label: real?.display };
  });

  const constraints = {};
  if (d.minAccuracy !== '') constraints.min_accuracy = Number(d.minAccuracy) / 100;

  const payload = {
    name: d.name,
    description: d.description,
    preset: d.preset,
    labels: d.labels.filter((l) => l.trim()),
    models: chosen,
    weights: d.weights,
    trials: Number(d.trials) || 3,
    constraints,
    tests: d.tests.filter((t) => t.input.trim()),
  };
  if (d.budget !== '') payload.budget_usd_per_1k_calls = Number(d.budget);
  if (d.latencyTarget !== '') payload.latency_target_ms = Number(d.latencyTarget);

  const created = await api('/api/projects', { method: 'POST', body: payload });
  state.draft = null;
  toast('Evaluation created.');
  location.hash = `#/p/${created.name}`;
}

/* -------------------------------------------------------- view: project */

function renderProjectHeader(p, activeTab) {
  return `
    <div class="project-header">
      <div class="project-header-top">
        <div>
          <div class="eyebrow">Evaluation Project</div>
          <h1 class="project-title">${esc(p.project || p.name)}</h1>
          <p class="lede mb0">${esc(p.description || 'Custom model benchmarking & evaluation suite.')}</p>
        </div>
        <div class="page-head-actions">
          <a class="btn btn-primary" href="#/p/${esc(p.name)}/run" data-link>
            <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>
            <span>Run sweep</span>
          </a>
          <div class="dropdown">
            <button class="btn dropdown-toggle" aria-label="Evaluation actions" data-dropdown-toggle>
              <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><circle cx="12" cy="5" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="12" cy="19" r="2"/></svg>
              <span>Manage</span>
              <span class="caret">▾</span>
            </button>
            <div class="dropdown-menu">
              <button class="dropdown-item" data-act="dup-proj" data-name="${esc(p.name)}">
                <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>
                Duplicate evaluation
              </button>
              <button class="dropdown-item" data-act="arch-proj" data-name="${esc(p.name)}" data-on="${p.archived ? '0' : '1'}">
                <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><rect width="20" height="5" x="2" y="3" rx="1"/><path d="M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8M10 12h4"/></svg>
                ${p.archived ? 'Restore evaluation' : 'Archive evaluation'}
              </button>
              <div class="dropdown-divider"></div>
              <button class="dropdown-item danger" data-act="del-proj" data-name="${esc(p.name)}">
                <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                Delete evaluation
              </button>
            </div>
          </div>
        </div>
      </div>
      <nav class="project-tabs" aria-label="Project Sub-navigation">
        <a href="#/p/${esc(p.name)}" data-link class="project-tab ${activeTab === 'overview' ? 'active' : ''}">Overview</a>
        <a href="#/p/${esc(p.name)}/results" data-link class="project-tab ${activeTab === 'results' ? 'active' : ''}">Results &amp; Leaderboard</a>
        <a href="#/p/${esc(p.name)}/priorities" data-link class="project-tab ${activeTab === 'priorities' ? 'active' : ''}">Priorities &amp; Weights</a>
        <a href="#/p/${esc(p.name)}/examples" data-link class="project-tab ${activeTab === 'examples' ? 'active' : ''}">Test Examples (${p.tests?.length || 0})</a>
        <a href="#/p/${esc(p.name)}/history" data-link class="project-tab ${activeTab === 'history' ? 'active' : ''}">History &amp; Sweeps</a>
      </nav>
    </div>`;
}

async function viewProject(name) {
  crumbs({ label: 'Projects', href: '#/projects' }, { label: name });
  const p = await api(`/api/projects/${name}`);
  state.project = p;
  const pre = p.preflight;

  const modelRows = p.models.map((m) => `
    <li class="model-line">
      <span>
        <span class="model-name">${esc(m.label)}</span>
        <span class="model-id">${esc(m.model)}</span>
      </span>
      ${m.simulated ? '<span class="pill mute">simulated · free</span>'
        : m.ready ? '<span class="pill ok">ready</span>'
        : `<span class="pill warn">needs a key</span>`}
    </li>`).join('');

  app().innerHTML = `
    ${renderProjectHeader(p, 'overview')}

    ${pre.blocked ? `<div class="callout bad"><p class="mb0">${esc(pre.blocked)}</p></div>` : ''}
    ${Object.keys(pre.skipped).length ? `
      <div class="callout warn">
        <p><strong>Some models will be skipped:</strong></p>
        <ul class="mb0">${Object.entries(pre.skipped).map(([k, v]) => `<li>${esc(k)} — ${esc(v)}</li>`).join('')}</ul>
      </div>` : ''}

    <div class="card">
      <div class="card-title"><h2>Ready to run</h2></div>
      <p class="muted">
        ${pre.planned_calls.toLocaleString()} model calls —
        ${esc(pre.runnable_models.length)} model${pre.runnable_models.length === 1 ? '' : 's'}
        × ${p.tests.length} example${p.tests.length === 1 ? '' : 's'}
        × ${p.run.trials} repeat${p.run.trials === 1 ? '' : 's'}.
      </p>
      <div class="btn-row">
        <button class="btn btn-primary btn-lg" data-act="run" ${pre.ok ? '' : 'disabled'}>Run the evaluation</button>
        <a class="btn" href="#/p/${esc(p.name)}/results" data-link>See last result</a>
        <a class="btn" href="#/p/${esc(p.name)}/history" data-link>History</a>
      </div>
    </div>

    <div class="split">
      <div>
        <div class="card">
          <div class="card-title">
            <h2>Your examples <span class="muted small">(${p.tests.length})</span></h2>
            <a class="btn btn-sm" href="#/p/${esc(p.name)}/examples" data-link>Edit</a>
          </div>
          <div class="table-wrap">
            <table>
              <thead><tr><th>What goes in</th><th>Expected answer</th></tr></thead>
              <tbody>
                ${p.tests.slice(0, 8).map((t) => `
                  <tr>
                    <td>${esc(t.input.slice(0, 120))}${t.input.length > 120 ? '…' : ''}</td>
                    <td><code class="model-id">${esc(String(t.reference ?? '—').slice(0, 60))}</code></td>
                  </tr>`).join('')}
              </tbody>
            </table>
          </div>
          ${p.tests.length > 8 ? `<p class="small muted" style="margin-top:.6rem">…and ${p.tests.length - 8} more.</p>` : ''}
        </div>
      </div>
      <div>
        <div class="card">
          <div class="card-title">
            <h2>What matters</h2>
            <a class="btn btn-sm" href="#/p/${esc(p.name)}/priorities" data-link>Change</a>
          </div>
          <p>${esc(p.weights_sentence)}</p>
          ${p.constraint_sentences.length ? `
            <p class="small"><strong>Hard limits</strong></p>
            <ul class="small muted">${p.constraint_sentences.map((s) => `<li>${esc(s)}</li>`).join('')}</ul>`
            : '<p class="small muted">No hard limits set — every model will be ranked.</p>'}
        </div>
        <div class="card">
          <h2>Models compared</h2>
          <ul class="model-list">${modelRows}</ul>
        </div>
      </div>
    </div>`;

  app().querySelectorAll('[data-act="dup-proj"]').forEach((b) => b.addEventListener('click', () => duplicateProject(b.dataset.name)));
  app().querySelectorAll('[data-act="arch-proj"]').forEach((b) => b.addEventListener('click', () => archiveProject(b.dataset.name, b.dataset.on === '1')));
  app().querySelectorAll('[data-act="del-proj"]').forEach((b) => b.addEventListener('click', () => deleteProject(b.dataset.name)));
}

/* ------------------------------------------------------------ view: run */

async function viewRun(name) {
  crumbs({ label: 'Projects', href: '#/projects' }, { label: name, href: `#/p/${name}` }, { label: 'Live Sweep' });
  const job = await api(`/api/projects/${name}/run`, { method: 'POST', body: {} });
  state.job = job;
  renderRun(name, job);
  state.poll = setInterval(async () => {
    try {
      const snap = await api(`/api/jobs/${job.id}`);
      state.job = snap;
      renderRun(name, snap);
      if (snap.status === 'done') {
        clearInterval(state.poll); state.poll = null;
        state.result = snap.result;
        location.hash = `#/p/${name}/results`;
      } else if (snap.status === 'error') {
        clearInterval(state.poll); state.poll = null;
      }
    } catch (error) {
      clearInterval(state.poll); state.poll = null;
      renderError(error);
    }
  }, 600);
}

function renderRun(name, job) {
  const percent = Math.round((job.fraction || 0) * 100);
  const feed = (job.recent || []).slice(-25).reverse().map((r) => {
    const cls = r.status !== 'ok' ? 'er' : r.passed ? 'ok' : 'no';
    const body = r.status !== 'ok' ? (r.error || 'error') : r.output || '(empty)';
    return `<div class="${cls}">[${r.passed ? 'PASS' : 'TEST'}] ${esc(r.model)} · ${esc(r.test)} — ${esc(body.slice(0, 110))}</div>`;
  }).join('');

  app().innerHTML = `
    <div class="page-head">
      <div>
        <div class="eyebrow">Running Evaluation Sweep</div>
        <h1>${esc(name)}</h1>
      </div>
    </div>
    ${job.status === 'error' ? `
      <div class="card">
        <div class="callout bad"><p class="mb0"><strong>The run stopped.</strong> ${esc(job.error)}</p></div>
        ${job.error_detail ? `<details><summary>Technical detail</summary><pre>${esc(job.error_detail)}</pre></details>` : ''}
        <p class="btn-row"><a class="btn" href="#/p/${esc(name)}" data-link>Back to the evaluation</a></p>
      </div>` : `
      <div class="card">
        <div class="card-header">
          <h2 class="card-title">${job.completed.toLocaleString()} of ${(job.planned || 0).toLocaleString()} calls done</h2>
          ${job.eta_s != null ? `<span class="badge-tag live-tag"><span class="dot live"></span>~${Math.ceil(job.eta_s)}s remaining</span>` : ''}
        </div>
        <div class="progress"><i style="width:${percent}%"></i></div>
        <p class="small muted">Every answer is graded as it arrives. You can leave this page — the sweep continues in background.</p>
        ${feed ? `<div class="feed">${feed}</div>` : ''}
      </div>`}`;
}

/* -------------------------------------------------------- view: results */

async function viewResults(name, params) {
  crumbs({ label: 'Projects', href: '#/projects' }, { label: name, href: `#/p/${name}` }, { label: 'Results' });
  const p = state.project?.name === name ? state.project : await api(`/api/projects/${name}`);
  state.project = p;
  // `?run=` asks for one specific sweep; without it the newest one is shown.
  // The cached result is only reusable when it is already that same run.
  const wanted = params ? params.get('run') : null;
  const cached = state.result;
  const usable = cached && cached.project === name && cached.run_id
    && (!wanted || cached.run_id === wanted);
  const result = usable
    ? cached
    : await api(`/api/projects/${name}/result${wanted ? `?run_id=${encodeURIComponent(wanted)}` : ''}`);
  state.result = result;
  renderResults(name, result, p);
}

function renderResults(name, result, p) {
  const v = result.verdict;
  const ranked = result.rows.filter((r) => r.status === 'ranked');
  const out = result.rows.filter((r) => r.status !== 'ranked');
  const maxAccuracy = Math.max(...result.rows.map((r) => r.accuracy || 0), 0.0001);

  const rankBadge = (i) => {
    if (i === 0) return '<span class="rank-badge gold">1</span>';
    if (i === 1) return '<span class="rank-badge silver">2</span>';
    if (i === 2) return '<span class="rank-badge bronze">3</span>';
    return `<span class="rank-badge">${i + 1}</span>`;
  };

  const row = (r, i) => `
    <tr class="${r.status === 'ranked' && i === 0 ? 'is-winner' : ''} ${r.status !== 'ranked' ? 'is-out' : ''}">
      <td class="num">${r.status === 'ranked' ? rankBadge(i) : '—'}</td>
      <td>
        <div class="model-name">${esc(r.display)}</div>
        <div class="model-id">${esc(r.model)}</div>
      </td>
      <td>
        ${esc(r.plain.accuracy)}
        <div class="bar ${i === 0 && r.status === 'ranked' ? 'good' : ''}">
          <i style="width:${Math.round(((r.accuracy || 0) / maxAccuracy) * 100)}%"></i>
        </div>
      </td>
      <td>${esc(r.plain.cost)}</td>
      <td>${esc(r.plain.latency)}<div class="small muted">${esc(r.plain.speed)}</div></td>
      <td class="num">${r.status === 'ranked' ? fixed(r.composite) : '<span class="pill bad">ruled out</span>'}</td>
    </tr>`;

  app().innerHTML = `
    ${p ? renderProjectHeader(p, 'results') : `
      <div class="page-head">
        <div class="eyebrow">${result.hypothetical ? 'What-if — nothing was re-run' : 'Result'}</div>
        <h1>${esc(name)}</h1>
      </div>`}

    <div class="card verdict ${v.confidence === 'low' ? 'low' : v.confidence === 'none' ? 'none' : ''}">
      <h1>${esc(v.headline)}</h1>
      <p class="body">${esc(v.body)}</p>
      ${v.because ? `<p class="small muted">${esc(v.because)}</p>` : ''}
      ${v.trade_offs?.length ? `<ul>${v.trade_offs.map((t) => `<li>${esc(t)}</li>`).join('')}</ul>` : ''}
      ${v.caveat ? `<div class="callout warn"><p class="mb0">${esc(v.caveat)}</p></div>` : ''}
    </div>

    ${v.disqualified?.length ? `
      <div class="card">
        <h2>Ruled out</h2>
        ${v.disqualified.map((d) => `
          <div class="callout bad">
            <p><strong>${esc(d.headline)}</strong> ${esc(d.reason)}</p>
            <p class="small mb0 muted">${esc(d.fix)}</p>
          </div>`).join('')}
      </div>` : ''}

    <div class="card">
      <div class="card-header">
        <h2 class="card-title">Every model, side by side</h2>
        <span class="badge-tag">${result.rows.length} models evaluated</span>
      </div>
      <div class="table-wrap">
        <table>
          <thead><tr>
            <th class="num">#</th><th>Model</th><th>Gets it right</th>
            <th>Cost per 1,000</th><th>Typical wait</th><th class="num">Overall</th>
          </tr></thead>
          <tbody>${ranked.map(row).join('')}${out.map((r) => row(r, -1)).join('')}</tbody>
        </table>
      </div>
      <p class="small muted" style="margin-top:.7rem">
        “Overall” blends the three columns using your priorities. It is only comparable within this table.
      </p>
    </div>

    <div class="split" style="margin-top: 1.35rem;">
      <div class="card" style="margin-top: 0;">
        <h2>What if your priorities changed?</h2>
        <p class="hint">Move a slider and the ranking is recalculated from the answers already
        collected. Nothing is re-run and nothing is charged.</p>
        ${['accuracy', 'cost', 'latency'].map((metric) => {
          const meta = state.catalog?.metric_language?.[metric] || {};
          const weight = result.weights[metric] ?? 0;
          return `
            <div class="weight">
              <div class="weight-label">${esc(meta.slider || metric)}</div>
              <div class="weight-value" data-out="${metric}">${Math.round(weight * 100)}</div>
              <input type="range" min="0" max="100" step="5" value="${Math.round(weight * 100)}" data-whatif="${metric}">
            </div>`;
        }).join('')}
        <div class="btn-row">
          <button class="btn btn-primary" data-act="whatif" data-name="${esc(name)}">Recalculate</button>
          ${result.hypothetical ? `<a class="btn" href="#/p/${esc(name)}/results" data-link data-reset="1">Back to real result</a>` : ''}
        </div>
      </div>

      <div>
        ${result.notes?.length ? `
          <div class="card" style="margin-top: 0;">
            <h2>Worth knowing</h2>
            <ul class="muted">${result.notes.map((n) => `<li>${esc(n)}</li>`).join('')}</ul>
          </div>` : ''}

        <div class="card" style="${result.notes?.length ? 'margin-top: 1.25rem;' : 'margin-top: 0;'}">
          <h2>Run metrics &amp; summary</h2>
          <div class="stat-row" style="grid-template-columns: repeat(2, 1fr); margin-bottom: 0;">
            ${result.totals.calls ? `<div class="stat"><div class="k">Calls made</div><div class="v">${result.totals.calls.toLocaleString()}</div></div>` : ''}
            ${result.totals.cost_usd != null ? `<div class="stat"><div class="k">Spent</div><div class="v">$${result.totals.cost_usd.toFixed(4)}</div></div>` : ''}
            ${result.totals.duration_s ? `<div class="stat"><div class="k">Took</div><div class="v">${result.totals.duration_s}s</div></div>` : ''}
            ${result.totals.errors != null ? `<div class="stat"><div class="k">Errors</div><div class="v">${result.totals.errors}</div></div>` : ''}
          </div>
          <div class="btn-row" style="margin-top:1.25rem">
            <a class="btn" href="#/p/${esc(name)}" data-link>Back to evaluation</a>
            <a class="btn" href="#/p/${esc(name)}/history" data-link>Compare with past runs</a>
          </div>
        </div>
      </div>
    </div>`;

  if (p) {
    app().querySelectorAll('[data-act="dup-proj"]').forEach((b) => b.addEventListener('click', () => duplicateProject(b.dataset.name)));
    app().querySelectorAll('[data-act="arch-proj"]').forEach((b) => b.addEventListener('click', () => archiveProject(b.dataset.name, b.dataset.on === '1')));
    app().querySelectorAll('[data-act="del-proj"]').forEach((b) => b.addEventListener('click', () => deleteProject(b.dataset.name)));
  }
}

/* ----------------------------------------------------- view: priorities */

async function viewPriorities(name) {
  crumbs({ label: 'Projects', href: '#/projects' }, { label: name, href: `#/p/${name}` }, { label: 'Priorities' });
  const p = state.project?.name === name ? state.project : await api(`/api/projects/${name}`);
  state.project = p;
  const weights = p.weights;

  app().innerHTML = `
    ${renderProjectHeader(p, 'priorities')}

    <div class="card">
      <h2>Weights &amp; Priorities</h2>
      <p class="lede">This is the only thing that decides who wins. Two teams running the same
      models on the same examples can correctly reach opposite conclusions here.</p>
      ${['accuracy', 'cost', 'latency'].map((metric) => {
        const meta = state.catalog?.metric_language?.[metric] || {};
        return `
          <div class="weight">
            <div class="weight-label">${esc(meta.slider || metric)}<small>${esc(meta.question || '')}</small></div>
            <div class="weight-value" data-out="${metric}">${Math.round((weights[metric] || 0) * 100)}</div>
            <input type="range" min="0" max="100" step="5" value="${Math.round((weights[metric] || 0) * 100)}" data-weight="${metric}">
          </div>`;
      }).join('')}
      <div class="callout" id="weights-sentence"><p class="mb0">${esc(p.weights_sentence)}</p></div>
    </div>
    <div class="card">
      <h2>Hard limits</h2>
      <p class="hint">Break one of these and a model is ruled out, not just ranked lower. Leave blank for no limit.</p>
      <div class="field-row">
        <div class="field">
          <label for="c-acc">Minimum accuracy (out of 100)</label>
          <input id="c-acc" type="number" min="0" max="100" step="1"
                 value="${p.constraints.min_accuracy != null ? Math.round(p.constraints.min_accuracy * 100) : ''}">
        </div>
        <div class="field">
          <label for="c-cost">Maximum cost per 1,000 uses ($)</label>
          <input id="c-cost" type="number" min="0" step="0.01"
                 value="${p.constraints.max_cost_per_1k_calls_usd ?? ''}">
        </div>
      </div>
      <div class="field-row">
        <div class="field">
          <label for="c-p95">Slowest acceptable answer (ms)</label>
          <input id="c-p95" type="number" min="0" step="100" value="${p.constraints.max_latency_p95_ms ?? ''}">
        </div>
        <div class="field">
          <label for="c-trials">Repeats per example</label>
          <input id="c-trials" type="number" min="1" max="20" value="${p.run.trials}">
        </div>
      </div>
    </div>
    <div class="btn-row">
      <button class="btn btn-primary" data-act="save-priorities" data-name="${esc(name)}">Save changes</button>
      <a class="btn" href="#/p/${esc(name)}" data-link>Cancel</a>
    </div>`;

  state.draft = { weights: { ...weights } };

  app().querySelectorAll('[data-act="dup-proj"]').forEach((b) => b.addEventListener('click', () => duplicateProject(b.dataset.name)));
  app().querySelectorAll('[data-act="arch-proj"]').forEach((b) => b.addEventListener('click', () => archiveProject(b.dataset.name, b.dataset.on === '1')));
  app().querySelectorAll('[data-act="del-proj"]').forEach((b) => b.addEventListener('click', () => deleteProject(b.dataset.name)));
}

/* ------------------------------------------------------- view: examples */

async function viewExamples(name) {
  crumbs({ label: 'Projects', href: '#/projects' }, { label: name, href: `#/p/${name}` }, { label: 'Test Examples' });
  const p = state.project?.name === name ? state.project : await api(`/api/projects/${name}`);
  state.project = p;
  state.draft = { tests: p.tests.map((t) => ({ ...t, reference: t.reference ?? '' })) };

  const answerLabel = p.preset?.answer_label || 'Expected answer';
  app().innerHTML = `
    ${renderProjectHeader(p, 'examples')}

    ${p.editable ? '' : `
      <div class="callout warn"><p class="mb0">This project keeps its examples in more than one
      file, or uses custom code, so they cannot be safely edited here. Edit the files on disk.</p></div>`}
    <div class="card">
      <div class="table-wrap">
        <table>
          <thead><tr>
            <th style="width:50%">What goes in</th>
            <th style="width:38%">${esc(answerLabel)}</th>
            <th></th>
          </tr></thead>
          <tbody id="tests-body"></tbody>
        </table>
      </div>
      <div class="btn-row" style="margin-top:.8rem">
        <button class="btn btn-sm" data-act="add-test">Add an example</button>
        <button class="btn btn-sm" data-act="paste-tests">Paste a list</button>
      </div>
    </div>
    <div class="btn-row">
      <button class="btn btn-primary" data-act="save-tests" data-name="${esc(name)}" ${p.editable ? '' : 'disabled'}>Save examples</button>
      <a class="btn" href="#/p/${esc(name)}" data-link>Cancel</a>
    </div>`;
  renderTestRows();

  app().querySelectorAll('[data-act="dup-proj"]').forEach((b) => b.addEventListener('click', () => duplicateProject(b.dataset.name)));
  app().querySelectorAll('[data-act="arch-proj"]').forEach((b) => b.addEventListener('click', () => archiveProject(b.dataset.name, b.dataset.on === '1')));
  app().querySelectorAll('[data-act="del-proj"]').forEach((b) => b.addEventListener('click', () => deleteProject(b.dataset.name)));
}

function renderTestRows() {
  const body = $('#tests-body');
  if (!body) return;
  const preset = state.catalog?.presets?.find((p) => p.id === state.project?.preset?.id);
  body.innerHTML = state.draft.tests.map((t, i) => `
    <tr>
      <td><textarea data-test="${i}" data-key="input">${esc(t.input)}</textarea></td>
      <td><textarea data-test="${i}" data-key="reference" placeholder="${esc(preset?.answer_hint || '')}">${esc(t.reference)}</textarea></td>
      <td><button class="btn btn-sm" data-act="drop-test" data-i="${i}" aria-label="Remove example">✕</button></td>
    </tr>`).join('');
}

/* -------------------------------------------------------- view: history */

async function viewHistory(name) {
  crumbs({ label: 'Projects', href: '#/projects' }, { label: name, href: `#/p/${name}` }, { label: 'History' });
  const p = state.project?.name === name ? state.project : await api(`/api/projects/${name}`);
  state.project = p;
  const history = await api(`/api/projects/${name}/history`);
  const isCompleteStatus = (s) => !s || s === 'completed' || s === 'complete' || s === 'done';
  const groups = groupRunsByDate(history.runs);

  app().innerHTML = `
    ${renderProjectHeader(p, 'history')}

    ${groups.length ? `
      ${groups.map((g) => `
        <div class="run-date-group">
          <div class="run-date-heading">
            <div class="run-date-title">
              <span>${esc(g.date)}</span>
            </div>
            <span class="pill mute">${g.runs.length} run${g.runs.length === 1 ? '' : 's'}</span>
          </div>
          <div class="grid-scroll"><table class="data">
            <thead><tr><th>Time</th><th>Top Model</th><th class="num">Calls</th><th class="num">Cost</th><th>Status</th><th class="right">Actions</th></tr></thead>
            <tbody>${g.runs.map((r) => `
              <tr>
                <td>
                  <strong>${esc(formatTime(r.started_at) || '—')}</strong>
                  <span class="hint font-mono">(${esc(timeAgo(r.started_at))})</span>
                  <br><span class="hint font-mono small">${esc(r.run_id)}</span>
                </td>
                <td>${r.winner ? `<span class="pill winner">★ ${esc(r.winner)}</span>` : '<span class="muted">—</span>'}</td>
                <td class="num">${r.n_results != null ? r.n_results.toLocaleString() : '—'}</td>
                <td class="num">${r.total_cost_usd != null ? '$' + Number(r.total_cost_usd).toFixed(4) : '—'}</td>
                <td>${isCompleteStatus(r.status) ? '<span class="status-clean good">complete</span>' : `<span class="pill warn">${esc(r.status)}</span>`}</td>
                <td class="right">
                  <div class="dropdown">
                    <button class="icon-btn dropdown-toggle" aria-label="Run actions" data-dropdown-toggle>
                      <svg viewBox="0 0 24 24" width="15" height="15" fill="currentColor"><circle cx="12" cy="5" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="12" cy="19" r="2"/></svg>
                    </button>
                    <div class="dropdown-menu">
                      <a class="dropdown-item" href="#/p/${esc(name)}/results?run=${esc(r.run_id)}" data-link>
                        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/></svg>
                        View results
                      </a>
                      <a class="dropdown-item" href="#/p/${esc(name)}/cases/${esc(r.run_id)}" data-link>
                        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><rect width="18" height="18" x="3" y="3" rx="2"/><path d="M3 9h18M9 21V9"/></svg>
                        Inspect cases
                      </a>
                      <div class="dropdown-divider"></div>
                      <button class="dropdown-item danger" data-rmrun="${esc(r.run_id)}" data-proj="${esc(name)}">
                        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                        Delete run
                      </button>
                    </div>
                  </div>
                </td>
              </tr>`).join('')}</tbody>
          </table></div>
        </div>`).join('')}
      ${renderTrend(history.models)}` : '<div class="empty"><p>No runs yet.</p></div>'}
    <p class="btn-row"><a class="btn" href="#/p/${esc(name)}" data-link>Back to the evaluation</a></p>`;

  app().querySelectorAll('[data-act="dup-proj"]').forEach((b) => b.addEventListener('click', () => duplicateProject(b.dataset.name)));
  app().querySelectorAll('[data-act="arch-proj"]').forEach((b) => b.addEventListener('click', () => archiveProject(b.dataset.name, b.dataset.on === '1')));
  app().querySelectorAll('[data-act="del-proj"]').forEach((b) => b.addEventListener('click', () => deleteProject(b.dataset.name)));

  app().querySelectorAll('[data-rmrun]').forEach((b) =>
    b.addEventListener('click', () => deleteRun(b.dataset.proj, b.dataset.rmrun)));
}

/** Accuracy over time, drawn as inline SVG so there is no chart library to load. */
function renderTrend(series) {
  const models = Object.entries(series).filter(([, points]) => points.length > 1);
  if (!models.length) return '';
  const width = 640, height = 200, pad = 30;
  const colors = ['#2563eb', '#16a34a', '#d97706', '#dc2626', '#7c3aed'];
  const count = Math.max(...models.map(([, p]) => p.length));

  const lines = models.map(([key, points], index) => {
    const path = points.map((point, i) => {
      const x = pad + (i / Math.max(count - 1, 1)) * (width - pad * 2);
      const y = height - pad - (point.accuracy || 0) * (height - pad * 2);
      return `${i ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(' ');
    return `<path d="${path}" fill="none" stroke="${colors[index % colors.length]}" stroke-width="2"/>`;
  }).join('');

  const legend = models.map(([key], index) =>
    `<span class="pill mute" style="color:${colors[index % colors.length]}">${esc(key)}</span>`
  ).join(' ');

  return `
    <div class="card">
      <h2>Accuracy over time</h2>
      <div class="table-wrap">
        <svg viewBox="0 0 ${width} ${height}" width="100%" height="${height}" role="img"
             aria-label="Accuracy of each model across past runs">
          <line x1="${pad}" y1="${height - pad}" x2="${width - pad}" y2="${height - pad}" stroke="currentColor" opacity=".2"/>
          <line x1="${pad}" y1="${pad}" x2="${pad}" y2="${height - pad}" stroke="currentColor" opacity=".2"/>
          <text x="4" y="${pad + 4}" font-size="10" fill="currentColor" opacity=".6">100</text>
          <text x="8" y="${height - pad + 4}" font-size="10" fill="currentColor" opacity=".6">0</text>
          ${lines}
        </svg>
      </div>
      <p class="small">${legend}</p>
    </div>`;
}

/* ------------------------------------------------------------- handlers */

document.addEventListener('click', async (event) => {
  const target = event.target.closest('[data-act], [data-preset], [data-model], [data-run]');
  if (!target) return;

  // wizard: job type
  if (target.dataset.preset) {
    state.draft.preset = target.dataset.preset;
    const preset = state.catalog.presets.find((p) => p.id === target.dataset.preset);
    if (preset) state.draft.weights = { ...preset.weights };
    renderWizard();
    return;
  }

  // wizard: model toggle
  if (target.dataset.model) {
    const key = target.dataset.model;
    const models = state.draft.models;
    const at = models.indexOf(key);
    if (at >= 0) models.splice(at, 1); else models.push(key);
    target.setAttribute('aria-pressed', at < 0);
    return;
  }

  // history: view one stored run
  if (target.dataset.run) {
    event.preventDefault();
    const { run, name } = target.dataset;
    const result = await api(`/api/projects/${name}/result?run_id=${encodeURIComponent(run)}`);
    state.result = result;
    location.hash = `#/p/${name}/results`;
    return;
  }

  const action = target.dataset.act;
  try {
    if (action === 'next') {
      const problem = wizardValidate();
      if (problem) { toast(problem, true); return; }
      state.draft.step += 1;
      renderWizard();
    } else if (action === 'back') {
      state.draft.step -= 1;
      renderWizard();
    } else if (action === 'create') {
      target.disabled = true;
      await wizardCreate();
    } else if (action === 'add-label') {
      state.draft.labels.push('');
      renderWizard();
    } else if (action === 'drop-label') {
      state.draft.labels.splice(Number(target.dataset.i), 1);
      renderWizard();
    } else if (action === 'fill-example') {
      /* Nobody writes a good test case staring at an empty box. Drop a real
       * worked pair for this job type into the first free rows so the shape
       * of the answer is obvious, then let them edit over it. */
      const starter = (state.catalog?.presets || [])
        .find((p) => p.id === state.draft.preset)?.starter || [];
      starter.forEach(([input, reference]) => {
        const blank = state.draft.tests.find((t) => !t.input && !t.reference);
        if (blank) { blank.input = input; blank.reference = reference; }
        else { state.draft.tests.push({ input, reference }); }
      });
      toast('Filled in an example. Edit it, or add your own beneath.');
      if (location.hash.includes('/examples')) renderTestRows(); else renderWizard();
    } else if (action === 'add-test') {
      state.draft.tests.push({ input: '', reference: '' });
      if (location.hash.includes('/examples')) renderTestRows(); else renderWizard();
    } else if (action === 'drop-test') {
      state.draft.tests.splice(Number(target.dataset.i), 1);
      if (location.hash.includes('/examples')) renderTestRows(); else renderWizard();
    } else if (action === 'paste-tests') {
      pasteTests();
    } else if (action === 'run') {
      location.hash = `#/p/${state.project.name}/run`;
    } else if (action === 'save-priorities') {
      await savePriorities(target.dataset.name);
    } else if (action === 'save-tests') {
      await saveTests(target.dataset.name);
    } else if (action === 'whatif') {
      await runWhatIf(target.dataset.name);
    }
  } catch (error) {
    target.disabled = false;
    toast(error.message, true);
  }
});

document.addEventListener('input', (event) => {
  const el = event.target;

  if (el.dataset.bind) {
    state.draft[el.dataset.bind] = el.value;
  } else if (el.dataset.label != null) {
    state.draft.labels[Number(el.dataset.label)] = el.value;
  } else if (el.dataset.test != null) {
    state.draft.tests[Number(el.dataset.test)][el.dataset.key] = el.value;
  } else if (el.dataset.weight) {
    state.draft.weights[el.dataset.weight] = Number(el.value) / 100;
    const out = document.querySelector(`[data-out="${el.dataset.weight}"]`);
    if (out) out.textContent = el.value;
    const sentence = $('#weights-sentence');
    if (sentence) sentence.innerHTML = `<p class="mb0">${esc(weightSentence(state.draft.weights))}</p>`;
  } else if (el.dataset.whatif) {
    const out = document.querySelector(`[data-out="${el.dataset.whatif}"]`);
    if (out) out.textContent = el.value;
  }
});

/* ------------------------------------------------------------- actions */

function pasteTests() {
  const raw = prompt(
    'Paste one example per line, as:\n\nwhat goes in | expected answer\n\n' +
    'A tab or a comma works instead of the bar.'
  );
  if (!raw) return;
  const added = raw.split('\n').map((line) => line.trim()).filter(Boolean).map((line) => {
    const parts = line.split(/\s*[|\t]\s*/);
    if (parts.length < 2) {
      const comma = line.lastIndexOf(',');
      if (comma > 0) return { input: line.slice(0, comma).trim(), reference: line.slice(comma + 1).trim() };
      return { input: line, reference: '' };
    }
    return { input: parts[0], reference: parts.slice(1).join(' | ') };
  });
  state.draft.tests = state.draft.tests.filter((t) => t.input.trim()).concat(added);
  if (location.hash.includes('/examples')) renderTestRows(); else renderWizard();
  toast(`Added ${added.length} example${added.length === 1 ? '' : 's'}.`);
}

async function savePriorities(name) {
  const number = (id) => ($(id).value === '' ? null : Number($(id).value));
  const minAccuracy = number('#c-acc');
  const body = {
    weights: state.draft.weights,
    trials: Number($('#c-trials').value) || 1,
    constraints: {
      min_accuracy: minAccuracy == null ? null : minAccuracy / 100,
      max_cost_per_1k_calls_usd: number('#c-cost'),
      max_latency_p95_ms: number('#c-p95'),
    },
  };
  for (const [key, value] of Object.entries(body.constraints)) {
    if (value == null) delete body.constraints[key];
  }
  await api(`/api/projects/${name}`, { method: 'PUT', body });
  state.project = null;
  toast('Saved.');
  location.hash = `#/p/${name}`;
}

async function saveTests(name) {
  const tests = state.draft.tests.filter((t) => String(t.input).trim());
  if (!tests.length) { toast('Add at least one example.', true); return; }
  await api(`/api/projects/${name}/tests`, { method: 'PUT', body: { tests } });
  state.project = null;
  toast(`Saved ${tests.length} example${tests.length === 1 ? '' : 's'}.`);
  location.hash = `#/p/${name}`;
}

async function runWhatIf(name) {
  const weights = {};
  document.querySelectorAll('[data-whatif]').forEach((el) => {
    const value = Number(el.value) / 100;
    if (value > 0) weights[el.dataset.whatif] = value;
  });
  if (!Object.keys(weights).length) { toast('At least one slider has to be above zero.', true); return; }
  const result = await api(`/api/projects/${name}/whatif`, {
    method: 'POST',
    body: { weights, run_id: state.result?.run_id },
  });
  state.result = result;
  renderResults(name, result);
  toast('Recalculated from the answers already collected.');
}

/* ==================================================== destructive actions
 *
 * One helper for everything that removes something. It asks the server for
 * the plan first (every destructive endpoint takes dry_run and returns the
 * same shape either way), prints exactly what will go, and only then asks.
 * Anything irreversible additionally requires the name to be typed — the
 * rule recorded in AGENTS.md and docs/design/interaction-patterns.md.
 */

function closeModal() {
  $('#modal').hidden = true;
  $('#modal-body').innerHTML = '';
  $('#modal-actions').innerHTML = '';
}

function describePlan(plan) {
  const lines = [];
  const paths = plan.paths || plan.report_files || [];
  paths.slice(0, 8).forEach((path) => lines.push(path));
  if (paths.length > 8) lines.push(`… and ${paths.length - 8} more`);
  if (plan.runs_removed) lines.push(`${plan.runs_removed} run(s) of history`);
  if (plan.results_removed) lines.push(`${plan.results_removed} recorded call(s)`);
  if (plan.bytes) lines.push(`${Math.round(plan.bytes / 1024).toLocaleString()} KB`);
  if (plan.referenced_by?.length) lines.push(`referenced by: ${plan.referenced_by.join(', ')}`);
  return lines;
}

/** Show the plan, then run `commit` if the user confirms. */
async function confirmDestructive({ title, plan, typeToConfirm, danger = 'Delete', commit }) {
  const doomed = describePlan(plan);
  $('#modal-title').textContent = title;
  $('#modal-body').innerHTML = `
    <p>This removes:</p>
    <div class="doomed">${doomed.length ? doomed.map(esc).join('<br>') : 'nothing on disk'}</div>
    ${typeToConfirm
      ? `<div class="field">
           <label for="confirm-name">Type <strong>${esc(typeToConfirm)}</strong> to confirm</label>
           <input id="confirm-name" autocomplete="off" spellcheck="false">
         </div>`
      : '<p class="hint">This can be undone until you run a vacuum.</p>'}`;
  $('#modal-actions').innerHTML = `
    <button class="btn" id="modal-cancel" type="button">Cancel</button>
    <button class="btn btn-danger" id="modal-go" type="button" ${typeToConfirm ? 'disabled' : ''}>${esc(danger)}</button>`;
  $('#modal').hidden = false;

  const go = $('#modal-go');
  if (typeToConfirm) {
    const input = $('#confirm-name');
    input.focus();
    input.addEventListener('input', () => { go.disabled = input.value.trim() !== typeToConfirm; });
  } else {
    go.focus();
  }
  $('#modal-cancel').addEventListener('click', closeModal);
  go.addEventListener('click', async () => {
    go.disabled = true;
    try { await commit(); closeModal(); }
    catch (error) { closeModal(); toast(error.message, true); }
  });
}

/* ------------------------------------------------------- view: overview */

async function viewOverview() {
  crumbs({ label: 'Overview' });
  const { projects } = await api('/api/projects');
  state.projects = projects;

  const withRuns = projects.filter((p) => p.last_run);
  const spend = withRuns.reduce((sum, p) => sum + (p.last_run.total_cost_usd || 0), 0);
  const totalTests = projects.reduce((sum, p) => sum + (p.tests || 0), 0);
  const totalModels = projects.reduce((sum, p) => sum + (p.models || 0), 0);

  app().innerHTML = `
    <div class="page-head">
      <div>
        <div class="eyebrow">AI Engineering Studio</div>
        <h1>Overview</h1>
        <p class="lede">Empirical evaluations, latency benchmarks, and cost analysis across frontier &amp; local LLMs.
        Rank models on your real-world test cases and production constraints.</p>
      </div>
      <div class="btn-row">
        <a class="btn btn-primary" href="#/new" data-link>
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>
          <span>New evaluation</span>
        </a>
      </div>
    </div>

    <div class="stat-row">
      <div class="stat accent">
        <span class="k">Evaluations</span>
        <span class="v">${projects.length}</span>
        <span class="sub">${withRuns.length} sweep${withRuns.length === 1 ? '' : 's'} completed</span>
      </div>
      <div class="stat blue">
        <span class="k">Models Benchmarked</span>
        <span class="v">${totalModels}</span>
        <span class="sub">Across all projects</span>
      </div>
      <div class="stat good">
        <span class="k">Test Examples</span>
        <span class="v">${totalTests}</span>
        <span class="sub">Verified golden assertions</span>
      </div>
      <div class="stat">
        <span class="k">Cumulative Spend</span>
        <span class="v">${spend ? '$' + spend.toFixed(4) : '$0.00'}</span>
        <span class="sub">Last sweep of each eval</span>
      </div>
    </div>


    <div class="split-2col" style="margin-top: 1.25rem;">
      <div>
        <div class="card">
          <div class="card-header">
            <h2 class="card-title">Recent evaluation sweeps</h2>
            <a class="btn btn-sm" href="#/projects" data-link>View all</a>
          </div>
          ${withRuns.length ? `
            <div class="grid-scroll"><table class="data">
              <thead><tr><th>Evaluation</th><th>Top Model</th><th>When</th><th class="num">Cost</th><th class="right">Action</th></tr></thead>
              <tbody>${withRuns.map((p) => `
                <tr>
                  <td>
                    <a href="#/p/${esc(p.name)}" data-link><strong>${esc(p.name)}</strong></a>
                    ${p.description ? `<br><span class="hint">${esc(p.description.slice(0, 50))}${p.description.length > 50 ? '…' : ''}</span>` : ''}
                  </td>
                  <td>${p.last_run.winner ? `<span class="pill winner">★ ${esc(p.last_run.winner)}</span>` : '<span class="pill mute">—</span>'}</td>
                  <td class="small muted">${esc(timeAgo(p.last_run.started_at))}</td>
                  <td class="num">${p.last_run.total_cost_usd != null ? '$' + Number(p.last_run.total_cost_usd).toFixed(4) : '—'}</td>
                  <td class="row-actions">
                    <a class="btn btn-sm" href="#/p/${esc(p.name)}/results" data-link>Results</a>
                  </td>
                </tr>`).join('')}</tbody>
            </table></div>`
            : `<div class="empty">
                 <h2>No sweeps run yet</h2>
                 <p class="small muted">Run your first evaluation to generate comparative leaderboards and cost metrics.</p>
                 <p class="btn-row" style="justify-content:center"><a class="btn btn-primary" href="#/projects" data-link>Go to evaluations</a></p>
               </div>`}
        </div>
      </div>

      <div>
        <div class="card">
          <div class="card-header">
            <h2 class="card-title">CLI Quickstart</h2>
            <span class="badge-tag live-tag"><span class="dot live"></span>Offline-first</span>
          </div>
          <p class="small muted">Validate and execute evaluations locally with zero API keys using built-in simulated providers:</p>
          <pre><code># Validate project configuration
arena validate --project projects/support_triage

# Run sweep without UI
arena evaluate --project projects/support_triage</code></pre>
        </div>
      </div>
    </div>

    <div class="card" style="margin-top: 1.25rem;">
      <div class="card-header">
        <h2 class="card-title">Active AI projects</h2>
        <span class="badge-tag">${projects.length} project${projects.length === 1 ? '' : 's'}</span>
      </div>
      <div class="grid">
        ${projects.map((p) => `
          <a class="project-card" href="#/p/${esc(p.name)}" data-link>
            <h3>${esc(p.project || p.name)}</h3>
            <p class="small muted mb0">${esc(p.description || 'No description yet.')}</p>
            <div class="meta" style="margin-top:auto; padding-top:.4rem;">
              <span>${p.models} model${p.models === 1 ? '' : 's'} · ${p.tests} test${p.tests === 1 ? '' : 's'}</span>
              ${p.last_run?.winner ? `<br><span class="small" style="color:var(--accent)">Top: <strong>${esc(p.last_run.winner)}</strong></span>` : ''}
            </div>
          </a>`).join('')}
      </div>
    </div>

    <div class="grid-2col" style="margin-top: 1.25rem;">
      <details class="aws-expandable" open>
        <summary>Evaluation Methodology &amp; Constraints</summary>
        <div class="expand-body">
          <p class="small">Agent Arena applies three strict gates before ranking models:</p>
          <ul class="small muted" style="padding-left: 1.2rem; margin: .4rem 0;">
            <li><strong>Accuracy Floor:</strong> Models failing minimum precision are disqualified, not merely penalized.</li>
            <li><strong>Cost Ceiling:</strong> Hard max $ budget per 1,000 requests.</li>
            <li><strong>Latency P95:</strong> Real wall-clock latency limits for production readiness.</li>
          </ul>
          <p class="small muted mb0">Composite scores are normalized only across models satisfying all constraints.</p>
        </div>
      </details>

      <div class="card">
        <h2 class="card-title">System Status</h2>
        <div class="model-line" style="margin-top: .6rem;">
          <span>Engine Runtime</span>
          <span class="pill ok">Standard Library (Zero dependencies)</span>
        </div>
        <div class="model-line">
          <span>Provider Connectors</span>
          <span class="pill mute">Lazy SDK / Offline Fallbacks</span>
        </div>
      </div>
    </div>`;
}

/* ------------------------------------------------------- view: projects */

async function viewProjects() {
  crumbs({ label: 'Projects' });
  const { projects } = await api('/api/projects?all=1');
  state.projects = projects;

  const withRuns = projects.filter((p) => p.last_run);

  app().innerHTML = `
    <div class="page-head">
      <div>
        <div class="eyebrow">Evaluations Directory</div>
        <h1>Evaluations</h1>
        <p class="lede">All configured model evaluation benchmark projects and test suites.</p>
      </div>
      <div class="btn-row">
        <a class="btn btn-primary" href="#/new" data-link>
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>
          <span>New evaluation</span>
        </a>
      </div>
    </div>

    <div class="model-toolbar" style="margin-bottom: 1.25rem;">
      <div class="model-filter-chips" id="proj-filter-chips">
        <button class="filter-chip active" data-proj-filter="all">All (${projects.length})</button>
        <button class="filter-chip" data-proj-filter="active">Active (${projects.filter(p => !p.archived).length})</button>
        <button class="filter-chip" data-proj-filter="swept">Swept (${withRuns.length})</button>
        <button class="filter-chip" data-proj-filter="archived">Archived (${projects.filter(p => p.archived).length})</button>
      </div>
      <div class="model-search-box">
        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
          <circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line>
        </svg>
        <input type="search" id="proj-search" placeholder="Search evaluations by name or description…" aria-label="Search evaluations">
      </div>
    </div>

    ${projects.length ? `
      <div class="grid-scroll"><table class="data" id="proj-table">
        <thead><tr><th>Evaluation</th><th>Models</th><th>Examples</th><th>Last Sweep</th><th>Top Winner</th><th>Status</th><th class="right">Actions</th></tr></thead>
        <tbody>${projects.map((p) => `
          <tr class="${p.archived ? 'is-gone' : ''}" data-proj-name="${esc(p.name)}" data-proj-title="${esc(p.project || p.name)}" data-proj-desc="${esc(p.description || '')}" data-archived="${p.archived ? 'true' : 'false'}" data-has-run="${p.last_run ? 'true' : 'false'}">
            <td>
              <a href="#/p/${esc(p.name)}" data-link><strong>${esc(p.project || p.name)}</strong></a>
              ${p.project && p.project !== p.name ? `<span class="hint font-mono small"> (${esc(p.name)})</span>` : ''}
              ${p.description ? `<br><span class="hint">${esc((p.description || '').slice(0, 85))}${p.description.length > 85 ? '…' : ''}</span>` : ''}
            </td>
            <td class="num">${p.models}</td>
            <td class="num">${p.tests}</td>
            <td>${p.last_run ? esc(timeAgo(p.last_run.started_at)) : '<span class="hint">never</span>'}</td>
            <td>${p.last_run?.winner ? `<span class="pill winner">★ ${esc(p.last_run.winner)}</span>` : '<span class="pill mute">—</span>'}</td>
            <td>${p.archived ? '<span class="pill mute">archived</span>' : '<span class="pill ok">active</span>'}</td>
            <td class="right">
              <div class="dropdown">
                <button class="icon-btn dropdown-toggle" aria-label="Project actions" data-dropdown-toggle>
                  <svg viewBox="0 0 24 24" width="15" height="15" fill="currentColor"><circle cx="12" cy="5" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="12" cy="19" r="2"/></svg>
                </button>
                <div class="dropdown-menu">
                  <a class="dropdown-item" href="#/p/${esc(p.name)}" data-link>
                    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6M15 3h6v6M10 14L21 3"/></svg>
                    Open overview
                  </a>
                  <a class="dropdown-item" href="#/p/${esc(p.name)}/results" data-link>
                    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/></svg>
                    View results
                  </a>
                  <button class="dropdown-item" data-act="dup-proj" data-name="${esc(p.name)}">
                    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>
                    Duplicate
                  </button>
                  <button class="dropdown-item" data-act="arch-proj" data-name="${esc(p.name)}" data-on="${p.archived ? '0' : '1'}">
                    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><rect width="20" height="5" x="2" y="3" rx="1"/><path d="M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8M10 12h4"/></svg>
                    ${p.archived ? 'Restore' : 'Archive'}
                  </button>
                  <div class="dropdown-divider"></div>
                  <button class="dropdown-item danger" data-act="del-proj" data-name="${esc(p.name)}">
                    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                    Delete
                  </button>
                </div>
              </div>
            </td>
          </tr>`).join('')}</tbody>
      </table></div>`
      : `<div class="empty"><h2>No evaluations yet</h2>
           <p class="btn-row"><a class="btn btn-primary" href="#/new" data-link>Create one</a></p></div>`}`;

  const searchInput = document.getElementById('proj-search');
  const chipContainer = document.getElementById('proj-filter-chips');
  const table = document.getElementById('proj-table');

  function applyProjFilter() {
    if (!table) return;
    const query = (searchInput?.value || '').trim().toLowerCase();
    const activeChip = chipContainer?.querySelector('.filter-chip.active');
    const activeFilter = activeChip?.getAttribute('data-proj-filter') || 'all';

    const rows = table.querySelectorAll('tbody tr[data-proj-name]');
    rows.forEach((row) => {
      const name = (row.getAttribute('data-proj-name') || '').toLowerCase();
      const title = (row.getAttribute('data-proj-title') || '').toLowerCase();
      const desc = (row.getAttribute('data-proj-desc') || '').toLowerCase();
      const isArchived = row.getAttribute('data-archived') === 'true';
      const hasRun = row.getAttribute('data-has-run') === 'true';

      let matchesFilter = true;
      if (activeFilter === 'active') matchesFilter = !isArchived;
      else if (activeFilter === 'swept') matchesFilter = hasRun;
      else if (activeFilter === 'archived') matchesFilter = isArchived;

      const matchesSearch = !query || name.includes(query) || title.includes(query) || desc.includes(query);
      row.style.display = (matchesFilter && matchesSearch) ? '' : 'none';
    });
  }

  if (chipContainer) {
    chipContainer.addEventListener('click', (e) => {
      const btn = e.target.closest('.filter-chip');
      if (!btn) return;
      chipContainer.querySelectorAll('.filter-chip').forEach((c) => c.classList.remove('active'));
      btn.classList.add('active');
      applyProjFilter();
    });
  }

  if (searchInput) {
    searchInput.addEventListener('input', applyProjFilter);
  }

  app().querySelectorAll('[data-act="dup-proj"]').forEach((b) => b.addEventListener('click', () => duplicateProject(b.dataset.name)));
  app().querySelectorAll('[data-act="arch-proj"]').forEach((b) => b.addEventListener('click', () => archiveProject(b.dataset.name, b.dataset.on === '1')));
  app().querySelectorAll('[data-act="del-proj"]').forEach((b) => b.addEventListener('click', () => deleteProject(b.dataset.name)));
}

async function duplicateProject(name) {
  const copy = prompt(`Name for the copy of "${name}":`, `${name}_copy`);
  if (!copy) return;
  await api(`/api/projects/${name}/duplicate`, { method: 'POST', body: { name: copy } });
  toast(`Copied to ${copy}. Results were not copied.`);
  router();
}

async function archiveProject(name, archived) {
  await api(`/api/projects/${name}/archive`, { method: 'POST', body: { archived } });
  toast(archived ? `${name} archived.` : `${name} restored.`);
  router();
}

async function deleteProject(name) {
  const plan = await api(`/api/projects/${name}?dry_run=1`, { method: 'DELETE' });
  await confirmDestructive({
    title: `Delete ${name}?`,
    plan,
    typeToConfirm: name,
    danger: 'Delete everything',
    commit: async () => {
      await api(`/api/projects/${name}`, { method: 'DELETE' });
      toast(`${name} deleted.`);
      router();
    },
  });
}

/* ----------------------------------------------------------- view: runs */

async function viewAllRuns() {
  crumbs({ label: 'Runs' });
  const { projects } = await api('/api/projects');
  const lists = await Promise.all(projects.map(async (p) => {
    try {
      const { runs } = await api(`/api/projects/${p.name}/runs?limit=25`);
      return runs.map((r) => ({ ...r, project_name: p.name }));
    } catch { return []; }
  }));
  const runs = lists.flat().sort((a, b) => String(b.started_at).localeCompare(String(a.started_at)));
  const groups = groupRunsByDate(runs);
  const uniqueProjects = Array.from(new Set(runs.map((r) => r.project_name))).sort();
  const isCompleteStatus = (s) => !s || s === 'completed' || s === 'complete' || s === 'done';
  const completeRuns = runs.filter((r) => isCompleteStatus(r.status));
  const winnerRuns = runs.filter((r) => r.winner);

  app().innerHTML = `
    <div class="head-row">
      <div>
        <h1>Evaluation Runs</h1>
        <p class="lede">Benchmark sweeps separated by execution date and timestamp.</p>
      </div>
      <div>
        <span class="badge-tag"><strong>${runs.length}</strong> total run${runs.length === 1 ? '' : 's'}</span>
      </div>
    </div>

    ${runs.length ? `
      <div class="model-toolbar" style="margin-bottom: 1.5rem;">
        <div class="model-filter-chips" id="run-filter-chips">
          <button class="filter-chip active" data-run-filter="all">All (${runs.length})</button>
          <button class="filter-chip" data-run-filter="complete">Complete (${completeRuns.length})</button>
          <button class="filter-chip" data-run-filter="winner">With Winner (${winnerRuns.length})</button>
          ${uniqueProjects.length > 1 ? uniqueProjects.map((p) =>
            `<button class="filter-chip" data-run-filter="proj:${esc(p)}">${esc(p)}</button>`
          ).join('') : ''}
        </div>
        <div class="model-search-box">
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
            <circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line>
          </svg>
          <input type="search" id="run-search" placeholder="Filter runs by evaluation, run ID, model, or label…" aria-label="Filter runs" autocomplete="off">
        </div>
      </div>

      <div id="run-groups-container">
        ${groups.map((g) => `
          <div class="run-date-group">
            <div class="run-date-heading">
              <div class="run-date-title">
                <span>${esc(g.date)}</span>
              </div>
              <span class="pill mute">${g.runs.length} run${g.runs.length === 1 ? '' : 's'}</span>
            </div>
            <div class="grid-scroll"><table class="data">
              <thead><tr><th>Time</th><th>Evaluation</th><th>Top Model</th><th class="num">Calls</th><th class="num">Cost</th><th>Status</th><th class="right">Actions</th></tr></thead>
              <tbody>${g.runs.map((r) => `
                <tr data-project="${esc(r.project_name)}" data-status="${isCompleteStatus(r.status) ? 'complete' : esc(r.status)}" data-has-winner="${r.winner ? 'true' : 'false'}" data-search="${esc((r.project_name + ' ' + r.run_id + ' ' + (r.winner || '') + ' ' + (r.label || '') + ' ' + (isCompleteStatus(r.status) ? 'complete' : r.status) + ' ' + (formatTime(r.started_at) || '')).toLowerCase())}">
                  <td>
                    <strong>${esc(formatTime(r.started_at) || '—')}</strong>
                    <span class="hint font-mono">(${esc(timeAgo(r.started_at))})</span>
                    ${r.label ? `<br><span class="hint font-mono">${esc(r.label)}</span>` : ''}
                  </td>
                  <td>
                    <a href="#/p/${esc(r.project_name)}" data-link><strong>${esc(r.project_name)}</strong></a>
                    <br><span class="hint font-mono small">${esc(r.run_id)}</span>
                  </td>
                  <td>${r.winner ? `<span class="pill winner">${esc(r.winner)}</span>` : '<span class="muted">—</span>'}</td>
                  <td class="num">${r.n_results != null ? r.n_results.toLocaleString() : '—'}</td>
                  <td class="num">${r.total_cost_usd != null ? '$' + Number(r.total_cost_usd).toFixed(4) : '—'}</td>
                  <td>${isCompleteStatus(r.status) ? '<span class="status-clean good">complete</span>' : `<span class="pill warn">${esc(r.status)}</span>`}</td>
                  <td class="right">
                    <div class="dropdown">
                      <button class="icon-btn dropdown-toggle" aria-label="Run actions" data-dropdown-toggle>
                        <svg viewBox="0 0 24 24" width="15" height="15" fill="currentColor"><circle cx="12" cy="5" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="12" cy="19" r="2"/></svg>
                      </button>
                      <div class="dropdown-menu">
                        <a class="dropdown-item" href="#/p/${esc(r.project_name)}/results?run=${esc(r.run_id)}" data-link>
                          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/></svg>
                          View results
                        </a>
                        <a class="dropdown-item" href="#/p/${esc(r.project_name)}/cases/${esc(r.run_id)}" data-link>
                          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><rect width="18" height="18" x="3" y="3" rx="2"/><path d="M3 9h18M9 21V9"/></svg>
                          Inspect cases
                        </a>
                        <div class="dropdown-divider"></div>
                        <button class="dropdown-item danger" data-rmrun="${esc(r.run_id)}" data-proj="${esc(r.project_name)}">
                          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2 2v2"/></svg>
                          Delete run
                        </button>
                      </div>
                    </div>
                  </td>
                </tr>`).join('')}</tbody>
            </table></div>
          </div>`).join('')}
      </div>
      <div class="empty" id="run-filter-empty" style="display:none;margin-top:1.5rem;">
        <h2>No matching evaluation runs</h2>
        <p class="muted small">No sweeps match the selected filter criteria or search query.</p>
      </div>`
      : '<div class="empty"><h2>No runs yet</h2><p>Run an evaluation to start collecting benchmark results.</p></div>'}`;

  // Interactive Live Filter & Search across all runs
  let activeRunFilter = 'all';
  const searchInput = document.getElementById('run-search');
  const chipContainer = document.getElementById('run-filter-chips');

  function applyRunFilter() {
    const query = (searchInput?.value || '').trim().toLowerCase();
    const rows = app().querySelectorAll('.run-date-group tbody tr');
    rows.forEach((row) => {
      const proj = row.getAttribute('data-project') || '';
      const status = row.getAttribute('data-status') || '';
      const hasWinner = row.getAttribute('data-has-winner') === 'true';
      const search = row.getAttribute('data-search') || '';

      let matchesFilter = true;
      if (activeRunFilter === 'complete') {
        matchesFilter = status === 'complete';
      } else if (activeRunFilter === 'winner') {
        matchesFilter = hasWinner;
      } else if (activeRunFilter.startsWith('proj:')) {
        matchesFilter = proj === activeRunFilter.slice(5);
      }

      const matchesSearch = !query || search.includes(query);
      row.style.display = (matchesFilter && matchesSearch) ? '' : 'none';
    });

    let totalVisible = 0;
    app().querySelectorAll('.run-date-group').forEach((grp) => {
      const visibleRows = grp.querySelectorAll('tbody tr:not([style*="display: none"])');
      grp.style.display = visibleRows.length ? '' : 'none';
      totalVisible += visibleRows.length;
    });

    const emptyFilter = document.getElementById('run-filter-empty');
    if (emptyFilter) {
      emptyFilter.style.display = (runs.length > 0 && totalVisible === 0) ? '' : 'none';
    }
  }

  if (chipContainer) {
    chipContainer.addEventListener('click', (e) => {
      const btn = e.target.closest('.filter-chip');
      if (!btn) return;
      chipContainer.querySelectorAll('.filter-chip').forEach((c) => c.classList.remove('active'));
      btn.classList.add('active');
      activeRunFilter = btn.getAttribute('data-run-filter') || 'all';
      applyRunFilter();
    });
  }

  if (searchInput) {
    searchInput.addEventListener('input', applyRunFilter);
  }

  app().querySelectorAll('[data-rmrun]').forEach((b) =>
    b.addEventListener('click', () => deleteRun(b.dataset.proj, b.dataset.rmrun)));
}

async function deleteRun(project, runId) {
  const plan = await api(`/api/projects/${project}/runs/${runId}?dry_run=1`, { method: 'DELETE' });
  await confirmDestructive({
    title: 'Delete this run?',
    plan,
    danger: 'Delete run',
    commit: async () => {
      await api(`/api/projects/${project}/runs/${runId}`, { method: 'DELETE' });
      toast('Run deleted. It can be restored until you vacuum.');
      router();
    },
  });
}

/* ------------------------------------------------- view: per-case grid */

async function viewRunCases(name, runId) {
  crumbs({ label: 'Projects', href: '#/projects' }, { label: name, href: `#/p/${name}` }, { label: 'Cases' });
  const result = await api(`/api/projects/${name}/result?run_id=${encodeURIComponent(runId)}`);
  const rows = result.results || [];

  const byCase = new Map();
  const models = [];
  rows.forEach((r) => {
    if (!models.includes(r.model_key)) models.push(r.model_key);
    if (!byCase.has(r.test_id)) byCase.set(r.test_id, {});
    const cell = byCase.get(r.test_id);
    (cell[r.model_key] ||= []).push(r);
  });

  app().innerHTML = `
    <h1>Every case, every model</h1>
    <p class="lede">Where the models disagree is where the ranking is actually decided.
    A case they all get right carries no information.</p>
    ${byCase.size ? `
      <div class="grid-scroll"><table class="data">
        <thead><tr><th>case</th>${models.map((m) => `<th>${esc(m)}</th>`).join('')}</tr></thead>
        <tbody>${[...byCase.entries()].map(([testId, cells]) => `
          <tr>
            <td><code>${esc(testId)}</code></td>
            ${models.map((m) => {
              const list = cells[m] || [];
              if (!list.length) return '<td>—</td>';
              const passed = list.filter((r) => r.passed).length;
              const cls = passed === list.length ? 'ok' : (passed === 0 ? 'bad' : 'warn');
              return `<td><span class="pill ${cls}">${passed}/${list.length}</span>
                <br><span class="hint">${esc((list[0].output || '').slice(0, 40))}</span></td>`;
            }).join('')}
          </tr>`).join('')}</tbody>
      </table></div>`
      : '<div class="empty"><h2>No per-case detail stored for this run</h2></div>'}`;
}

/* ------------------------------------------------------ view: providers */

async function viewProviders() {
  crumbs({ label: 'Providers' });
  const [{ providers }, local] = await Promise.all([
    api('/api/providers'),
    api('/api/local').catch(() => ({ running: false, installed: false, models: [] })),
  ]);
  state.providers = providers;

  app().innerHTML = `
    <div class="page-head">
      <div>
        <h1>Providers</h1>
        <p class="lede">A profile is a named connection: an endpoint, a credential, and any
        headers it needs. Two profiles can point at the same vendor with different keys —
        that is the whole reason they exist.</p>
      </div>
    </div>

    <div class="card">
      <div class="head-row">
        <div><p class="card-title">Configured profiles</p>
          <p class="hint mb0">Hover a dot for what it means.</p></div>
        <button class="btn btn-sm" id="check-all">${icon('refresh')} Check all</button>
      </div>

          ${providers.length ? `
            <div class="grid-scroll" style="margin-top:.8rem">
              <table class="data">
                <thead><tr><th style="width:2.2rem"></th><th>profile</th>
                  <th>endpoint &amp; credential</th><th></th></tr></thead>
                <tbody>${providers.map((p) => `
                  <tr data-row="${esc(p.id)}">
                    <td><span data-status="${esc(p.id)}">${dot('', 'Not checked yet')}</span></td>
                    <td><strong>${esc(p.id)}</strong><br><span class="hint">${esc(p.kind)}</span></td>
                    <td><span class="model-id">${esc(p.base_url || 'vendor default')}</span>
                      <br><code class="model-id hint">${esc(p.api_key_ref || 'conventional env var')}</code></td>
                    <td>
                      <div class="row-actions">
                        <button class="icon-btn" data-test="${esc(p.id)}" title="Check this connection">${icon('plug')}</button>
                        <button class="icon-btn" data-disc="${esc(p.id)}" title="List the models it serves">${icon('refresh')}</button>
                        <button class="icon-btn" data-edit="${esc(p.id)}" title="Edit this profile">${icon('edit')}</button>
                        <button class="icon-btn" data-rmprov="${esc(p.id)}" title="Remove this profile and its stored key">${icon('trash')}</button>
                      </div>
                    </td>
                  </tr>
                  <tr data-models="${esc(p.id)}" hidden><td></td><td colspan="3"></td></tr>`).join('')}
                </tbody>
              </table>
            </div>`
        : `<p class="hint" style="margin-top:.6rem">No profiles yet. Models fall back to the
           vendor's conventional environment variable.</p>`}
    </div>

    <div class="split" style="margin-top:1rem">
      <div class="card" id="provider-form"></div>
      <div>
        <div class="card">
          <div class="head-row">
            <p class="card-title">On this machine</p>
            <span data-status="__local">${dot(local.running ? 'ok' : 'bad',
              local.running ? 'Running and reachable' : 'Not running')}</span>
          </div>
          <p class="hint">Local models cost nothing per call and never leave the box.</p>
          <div id="local-body">${renderLocal(local)}</div>
        </div>
      </div>
    </div>`;

  renderProviderForm(null);
  wireProviderRow();

  $('#check-all').addEventListener('click', () => providers.forEach((p) => checkProvider(p.id)));
  providers.forEach((p) => checkProvider(p.id));
}

function renderLocal(local) {
  if (!local.installed) {
    return `<p class="hint">Ollama is not installed.</p>
      <p class="btn-row"><a class="btn btn-sm" href="https://ollama.com">Install Ollama ${icon('external')}</a></p>`;
  }
  if (!local.running) {
    return `<p class="hint">Installed, but nothing is answering on
      <code>${esc(local.base_url || 'localhost:11434')}</code>.</p>
      <p class="btn-row"><button class="btn btn-sm btn-primary" id="local-start">${icon('play')} Start it</button></p>`;
  }
  return `
    <p class="hint">${local.models.length} model${local.models.length === 1 ? '' : 's'} available.</p>
    <div class="model-list">${local.models.map((m) => `
      <div class="model-line">
        ${dot('ok', 'Loaded and ready')}
        <span class="model-name">${esc(m)}</span>
      </div>`).join('') || '<p class="hint">None pulled yet — <code>ollama pull llama3.2</code></p>'}</div>
    <p class="btn-row"><button class="btn btn-sm" id="local-refresh">${icon('refresh')} Refresh</button></p>`;
}

function wireLocal() {
  if ($('#local-start')) {
    $('#local-start').addEventListener('click', async (event) => {
      const button = event.currentTarget;
      button.disabled = true;
      button.innerHTML = `${icon('refresh')} Starting…`;
      const report = await api('/api/local/start', { method: 'POST' });
      toast(report.detail, !report.running);
      await refreshLocal();
    });
  }
  if ($('#local-refresh')) $('#local-refresh').addEventListener('click', refreshLocal);
}

async function refreshLocal() {
  const local = await api('/api/local').catch(() => ({ running: false, installed: false, models: [] }));
  $('#local-body').innerHTML = renderLocal(local);
  const badge = app().querySelector('[data-status="__local"]');
  if (badge) {
    badge.innerHTML = dot(local.running ? 'ok' : 'bad',
      local.running ? 'Running and reachable' : 'Not running');
  }
  wireLocal();
}

/** Ask the server whether one profile is reachable, and colour its dot. */
async function checkProvider(id) {
  const cell = app().querySelector(`[data-status="${CSS.escape(id)}"]`);
  if (cell) cell.innerHTML = dot('busy', 'Checking…');
  try {
    const report = await api(`/api/providers/${id}/test`, { method: 'POST' });
    if (cell) {
      cell.innerHTML = report.ok
        ? dot('ok', `Reachable in ${report.latency_ms} ms`)
        : dot('bad', report.error || `Unreachable (HTTP ${report.status})`);
    }
  } catch (error) {
    if (cell) cell.innerHTML = dot('bad', error.message);
  }
}

function wireProviderRow() {
  wireLocal();

  app().querySelectorAll('[data-test]').forEach((b) =>
    b.addEventListener('click', () => checkProvider(b.dataset.test)));

  app().querySelectorAll('[data-edit]').forEach((b) =>
    b.addEventListener('click', () => {
      renderProviderForm(state.providers.find((p) => p.id === b.dataset.edit) || null);
      $('#provider-form').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }));

  app().querySelectorAll('[data-disc]').forEach((b) => b.addEventListener('click', async () => {
    const id = b.dataset.disc;
    const row = app().querySelector(`[data-models="${CSS.escape(id)}"]`);
    b.disabled = true;
    try {
      const { models } = await api(`/api/providers/${id}/discover`, { method: 'POST' });
      row.hidden = false;
      row.querySelector('td:last-child').innerHTML = models.length
        ? `<div class="model-list">${models.map((m) => `
             <div class="model-line">${dot('ok', 'Served by this endpoint')}
               <span class="model-name">${esc(m)}</span></div>`).join('')}</div>`
        : '<p class="hint mb0">This endpoint does not list its models. Many gateways do not.</p>';
    } finally { b.disabled = false; }
  }));

  app().querySelectorAll('[data-rmprov]').forEach((b) => b.addEventListener('click', async () => {
    const id = b.dataset.rmprov;
    const plan = await api(`/api/providers/${id}?dry_run=1`, { method: 'DELETE' });
    await confirmDestructive({
      title: `Remove ${id}?`,
      plan,
      danger: 'Remove',
      commit: async () => {
        await api(`/api/providers/${id}?purge_key=1`, { method: 'DELETE' });
        toast(`Removed ${id} and its stored credential.`);
        router();
      },
    });
  }));
}

/** One form for both add and edit — saving by an existing id replaces it. */
function renderProviderForm(profile) {
  const editing = Boolean(profile);
  $('#provider-form').innerHTML = `
    <p class="card-title">${editing ? `Edit ${esc(profile.id)}` : 'Add a profile'}</p>
    <p class="hint">${editing
      ? 'Saving replaces the stored profile.'
      : 'Point at any vendor or an OpenAI-compatible endpoint.'}</p>
    <div class="field-row" style="margin-top:.8rem">
      <div class="field"><label for="p-id">Name</label>
        <input id="p-id" placeholder="work_openai" value="${esc(profile?.id || '')}"
               ${editing ? 'readonly' : ''}></div>
      <div class="field"><label for="p-kind">Kind</label>
        <select id="p-kind">${
          ['openai', 'anthropic', 'gemini', 'openai_compatible', 'local', 'litellm']
            .map((k) => `<option ${profile?.kind === k ? 'selected' : ''}>${k}</option>`).join('')
        }</select></div>
    </div>
    <div class="field"><label for="p-url">Endpoint <span class="hint">optional</span></label>
      <input id="p-url" placeholder="https://gateway.internal/v1" value="${esc(profile?.base_url || '')}"></div>
    <div class="field"><label for="p-key">Credential</label>
      <input id="p-key" placeholder="\${env:OPENAI_API_KEY}" value="${esc(profile?.api_key_ref || '')}">
      <span class="hint">A reference is stored as written. A literal key is moved into your OS
      keyring, and only the reference is written to disk.</span></div>
    <div class="btn-row">
      <button class="btn btn-primary btn-sm" id="p-save">${icon('check')} ${editing ? 'Save changes' : 'Add profile'}</button>
      ${editing ? `<button class="btn btn-sm" id="p-cancel">Cancel</button>` : ''}
    </div>`;

  if ($('#p-cancel')) $('#p-cancel').addEventListener('click', () => renderProviderForm(null));

  $('#p-save').addEventListener('click', async () => {
    const body = {
      id: $('#p-id').value.trim(),
      kind: $('#p-kind').value,
      base_url: $('#p-url').value.trim() || null,
      api_key: $('#p-key').value.trim() || null,
    };
    if (!body.id) { toast('Give the profile a name.', true); return; }
    await api('/api/providers', { method: 'POST', body });
    toast(editing ? `Updated ${body.id}.` : `Added ${body.id}.`);
    router();
  });
}

/* ------------------------------------------------------- view: settings */

const SETTINGS_TABS = [
  [
    'general',
    'General',
    'Preferences & appearance',
    `<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>`
  ],
  [
    'defaults',
    'Defaults',
    'Default sweep parameters',
    `<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 21v-7"/><path d="M4 10V3"/><path d="M12 21v-9"/><path d="M12 8V3"/><path d="M20 21v-5"/><path d="M20 12V3"/><path d="M1 14h6"/><path d="M9 8h6"/><path d="M17 16h6"/></svg>`
  ],
  [
    'budgets',
    'Budgets & safety',
    'Spending caps & thresholds',
    `<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>`
  ],
  [
    'storage',
    'Storage',
    'Database cleanup & vacuum',
    `<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/></svg>`
  ],
  [
    'about',
    'About',
    'Engine version & docs',
    `<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>`
  ],
];

async function viewSettings(tab = 'general') {
  crumbs({ label: 'Settings' });
  const [settings, about] = await Promise.all([
    api('/api/settings'),
    api('/api/about').catch(() => ({
      version: state.catalog?.version || '2.0.0rc2',
      release_channel: 'Release Candidate (v2.0.0rc2)',
      license: 'MIT',
      author: 'Aditya Mhaske',
      python: '3.12+',
      platform: 'Darwin',
      yaml: true,
      scorers_count: 10,
      models_count: 30,
      pricing_as_of: '2026-09-02',
      storage_engine: 'SQLite 3 (WAL mode, local zero-network store)',
      docs_url: 'https://adityamhaske.github.io/agent-arena',
      repo_url: 'https://github.com/adityamhaske/agent-arena',
    })),
  ]);
  state.settings = settings;

  const tabs = SETTINGS_TABS.map(([slug, label, desc, iconSvg]) => `
    <a href="#/settings/${slug}" data-link class="settings-nav-item ${slug === tab ? 'on' : ''}">
      <div class="settings-nav-icon">${iconSvg}</div>
      <div class="settings-nav-text">
        <span class="settings-nav-title">${esc(label)}</span>
        <span class="settings-nav-desc">${esc(desc)}</span>
      </div>
    </a>`).join('');

  const currentTheme = storedTheme() || settings.theme || 'system';

  const panels = {
    general: () => `
      <div class="settings-card">
        <div class="settings-card-header">
          <div class="settings-card-icon">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="5"/><path d="M12 1v2M12 21v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M1 12h2M21 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4"/></svg>
          </div>
          <div>
            <h3>Theme & Appearance</h3>
            <p>Customize color palette, layout density, and data formatting.</p>
          </div>
        </div>

        <div style="margin-bottom:1.35rem;">
          <label class="setting-group-label">Color Theme</label>
          <div class="theme-picker" role="radiogroup" aria-label="Color theme">
            <button type="button" class="theme-card ${currentTheme === 'system' ? 'active' : ''}" data-theme-val="system" role="radio" aria-checked="${currentTheme === 'system'}">
              <div class="theme-preview preview-system">
                <div class="mini-window">
                  <div class="mini-header"><span class="mini-dot"></span><span class="mini-bar"></span></div>
                  <div class="mini-body"><div class="mini-col-l"></div><div class="mini-col-r"></div></div>
                </div>
              </div>
              <div class="theme-card-info">
                <div class="theme-card-title">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect width="20" height="14" x="2" y="3" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
                  <span>System</span>
                </div>
                <span class="theme-card-desc">Matches OS appearance</span>
              </div>
              <div class="theme-card-check">✓</div>
            </button>

            <button type="button" class="theme-card ${currentTheme === 'light' ? 'active' : ''}" data-theme-val="light" role="radio" aria-checked="${currentTheme === 'light'}">
              <div class="theme-preview preview-light">
                <div class="mini-window">
                  <div class="mini-header"><span class="mini-dot"></span><span class="mini-bar"></span></div>
                  <div class="mini-body"><div class="mini-card-l"></div><div class="mini-card-r"></div></div>
                </div>
              </div>
              <div class="theme-card-info">
                <div class="theme-card-title">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>
                  <span>Light</span>
                </div>
                <span class="theme-card-desc">Crisp daylight clarity</span>
              </div>
              <div class="theme-card-check">✓</div>
            </button>

            <button type="button" class="theme-card ${currentTheme === 'dark' ? 'active' : ''}" data-theme-val="dark" role="radio" aria-checked="${currentTheme === 'dark'}">
              <div class="theme-preview preview-dark">
                <div class="mini-window">
                  <div class="mini-header"><span class="mini-dot"></span><span class="mini-bar"></span></div>
                  <div class="mini-body"><div class="mini-card-l"></div><div class="mini-card-r"></div></div>
                </div>
              </div>
              <div class="theme-card-info">
                <div class="theme-card-title">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/></svg>
                  <span>Dark</span>
                </div>
                <span class="theme-card-desc">Deep slate contrast</span>
              </div>
              <div class="theme-card-check">✓</div>
            </button>
          </div>

          <select id="s-theme" data-set="theme" style="display:none;">
            <option value="system" ${currentTheme === 'system' ? 'selected' : ''}>System</option>
            <option value="light" ${currentTheme === 'light' ? 'selected' : ''}>Light</option>
            <option value="dark" ${currentTheme === 'dark' ? 'selected' : ''}>Dark</option>
          </select>
        </div>

        <div class="settings-grid-3">
          <div class="field">
            <label for="s-density">UI density</label>
            <select id="s-density" data-set="density">
              <option value="comfortable" ${settings.density === 'comfortable' ? 'selected' : ''}>Comfortable (Standard)</option>
              <option value="compact" ${settings.density === 'compact' ? 'selected' : ''}>Compact (Dense tables)</option>
            </select>
            <span class="hint">Row height and card padding</span>
          </div>

          <div class="field">
            <label for="s-num-fmt">Thousands separator</label>
            <select id="s-num-fmt" data-set="number_format">
              <option value="comma" ${settings.number_format === 'comma' ? 'selected' : ''}>Comma (1,000,000)</option>
              <option value="space" ${settings.number_format === 'space' ? 'selected' : ''}>Space (1 000 000)</option>
              <option value="none" ${settings.number_format === 'none' ? 'selected' : ''}>None (1000000)</option>
            </select>
            <span class="hint">Formatting for token and metric counts</span>
          </div>

          <div class="field">
            <label for="s-tz">Display timezone</label>
            <select id="s-tz" data-set="timezone">
              <option value="local" ${settings.timezone === 'local' ? 'selected' : ''}>Local (${Intl.DateTimeFormat().resolvedOptions().timeZone || 'System'})</option>
              <option value="UTC" ${settings.timezone === 'UTC' ? 'selected' : ''}>UTC (Universal Time)</option>
            </select>
            <span class="hint">Timezone used when displaying dates</span>
          </div>
        </div>
      </div>

      <div class="settings-card">
        <div class="settings-card-header">
          <div class="settings-card-icon">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
          </div>
          <div>
            <h3>Workspace & Navigation</h3>
            <p>Evaluation suite location and initial default view.</p>
          </div>
        </div>

        <div class="settings-grid-2">
          <div class="field">
            <label for="s-dir">Evaluations folder</label>
            <div class="input-with-prefix">
              <span class="input-prefix font-mono">📁 ./</span>
              <input id="s-dir" data-set="projects_dir" value="${esc(settings.projects_dir || 'projects')}" placeholder="projects">
            </div>
            <span class="hint">Relative directory where evaluations live</span>
          </div>

          <div class="field">
            <label for="s-landing">Default landing view</label>
            <select id="s-landing" data-set="default_landing">
              <option value="overview" ${settings.default_landing === 'overview' ? 'selected' : ''}>Overview Dashboard (#/)</option>
              <option value="projects" ${settings.default_landing === 'projects' ? 'selected' : ''}>Evaluations Directory (#/projects)</option>
              <option value="runs" ${settings.default_landing === 'runs' ? 'selected' : ''}>Global Runs Stream (#/runs)</option>
            </select>
            <span class="hint">Initial surface displayed on launch</span>
          </div>
        </div>
      </div>

      <div class="settings-card">
        <div class="settings-card-header">
          <div class="settings-card-icon">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect width="18" height="18" x="3" y="3" rx="2"/><polyline points="8 12 12 16 16 12"/><line x1="12" y1="8" x2="12" y2="16"/></svg>
          </div>
          <div>
            <h3>CLI Engine & Automation</h3>
            <p>Terminal verbosity and launch automation toggles.</p>
          </div>
        </div>

        <div class="field" style="margin-bottom:1.25rem;">
          <label for="s-log_level">Engine log level</label>
          <select id="s-log_level" data-set="log_level" style="max-width:420px;">
            <option value="warning" ${settings.log_level === 'warning' ? 'selected' : ''}>Warning (Quiet — recommended for clean CLI output)</option>
            <option value="info" ${settings.log_level === 'info' ? 'selected' : ''}>Info (Standard execution status)</option>
            <option value="debug" ${settings.log_level === 'debug' ? 'selected' : ''}>Debug (Verbose API traces)</option>
            <option value="error" ${settings.log_level === 'error' ? 'selected' : ''}>Error (Fatal errors only)</option>
          </select>
          <span class="hint">Controls stdout verbosity during CLI sweeps and background jobs</span>
        </div>

        <div class="settings-toggle-group">
          <div class="settings-toggle-row">
            <div class="toggle-info">
              <span class="toggle-title">Open browser automatically</span>
              <span class="toggle-desc">Automatically launch Agent Arena in your default browser on <code>arena ui</code> launch</span>
            </div>
            <label class="toggle-switch" for="s-open_browser">
              <input type="checkbox" id="s-open_browser" data-set="open_browser" ${settings.open_browser !== false ? 'checked' : ''}>
              <span class="toggle-slider"></span>
            </label>
          </div>

          <div class="settings-toggle-row">
            <div class="toggle-info">
              <span class="toggle-title">Check for newer versions</span>
              <span class="toggle-desc">Check PyPI for newer versions of Agent Arena on startup</span>
            </div>
            <label class="toggle-switch" for="s-update_check">
              <input type="checkbox" id="s-update_check" data-set="update_check" ${settings.update_check !== false ? 'checked' : ''}>
              <span class="toggle-slider"></span>
            </label>
          </div>
        </div>
      </div>`,

    defaults: () => `
      <div class="settings-card">
        <div class="settings-card-header">
          <div class="settings-card-icon">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
          </div>
          <div>
            <h3>Execution & Concurrency Seeds</h3>
            <p>Applied when scaffolding new evaluations. Existing evaluations preserve their <code>config.yaml</code>.</p>
          </div>
        </div>

        <div class="settings-grid-2">
          <div class="field">
            <label for="s-trials">Repeats per test case (Trials)</label>
            <div class="input-with-suffix">
              <input id="s-trials" type="number" min="1" max="50" data-set="defaults.trials" value="${esc(settings.defaults?.trials ?? 1)}">
              <span class="input-suffix">trials</span>
            </div>
            <span class="hint">Repeats each test prompt to detect non-deterministic variance</span>
          </div>

          <div class="field">
            <label for="s-concurrency">Concurrent model calls</label>
            <div class="input-with-suffix">
              <input id="s-concurrency" type="number" min="1" max="64" data-set="defaults.concurrency" value="${esc(settings.defaults?.concurrency ?? 4)}">
              <span class="input-suffix">workers</span>
            </div>
            <span class="hint">Max simultaneous in-flight provider API calls</span>
          </div>

          <div class="field">
            <label for="s-timeout">Per-call timeout</label>
            <div class="input-with-suffix">
              <input id="s-timeout" type="number" min="5" max="600" data-set="defaults.timeout_s" value="${esc(settings.defaults?.timeout_s ?? 120)}">
              <span class="input-suffix">seconds</span>
            </div>
            <span class="hint">Ceiling before timing out an LLM response</span>
          </div>

          <div class="field">
            <label for="s-retries">Retries after provider error</label>
            <div class="input-with-suffix">
              <input id="s-retries" type="number" min="0" max="10" data-set="defaults.retries" value="${esc(settings.defaults?.retries ?? 2)}">
              <span class="input-suffix">retries</span>
            </div>
            <span class="hint">Exponential backoff on transient 429 or 503 status codes</span>
          </div>
        </div>
      </div>

      <div class="settings-card">
        <div class="settings-card-header">
          <div class="settings-card-icon">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/></svg>
          </div>
          <div>
            <h3>Sampling & Output Constraints</h3>
            <p>Default generative hyperparameters for reproducible evaluation.</p>
          </div>
        </div>

        <div class="settings-grid-2">
          <div class="field">
            <label for="s-temperature">Sampling temperature</label>
            <div class="input-with-suffix">
              <input id="s-temperature" type="number" min="0" max="2" step="0.1" data-set="defaults.temperature" value="${esc(settings.defaults?.temperature ?? 0)}">
              <span class="input-suffix">temp</span>
            </div>
            <span class="hint">Evaluations default to 0 for maximum determinism and scoring reproducibility</span>
          </div>

          <div class="field">
            <label for="s-tokens">Max tokens ceiling</label>
            <div class="input-with-suffix">
              <input id="s-tokens" type="number" min="16" max="32768" data-set="defaults.max_tokens" value="${esc(settings.defaults?.max_tokens ?? 512)}">
              <span class="input-suffix">tokens</span>
            </div>
            <span class="hint">Safety completion token ceiling per test prompt</span>
          </div>
        </div>
      </div>`,

    budgets: () => `
      <div class="settings-card">
        <div class="settings-card-header">
          <div class="settings-card-icon">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>
          </div>
          <div>
            <h3>Spending Ceilings</h3>
            <p>Hard limits to prevent accidental runaway costs during large matrix sweeps.</p>
          </div>
        </div>

        <div class="settings-grid-3">
          <div class="field">
            <label for="s-max_run_usd">Max spend per sweep run</label>
            <div class="input-with-prefix">
              <span class="input-prefix font-mono">$</span>
              <input id="s-max_run_usd" type="number" step="0.01" min="0" placeholder="No limit" data-set="budgets.max_run_usd" value="${esc(settings.budgets?.max_run_usd ?? '')}">
            </div>
            <span class="hint">Hard dollar ceiling for the entire sweep</span>
          </div>

          <div class="field">
            <label for="s-max_model_usd">Max spend per model</label>
            <div class="input-with-prefix">
              <span class="input-prefix font-mono">$</span>
              <input id="s-max_model_usd" type="number" step="0.01" min="0" placeholder="No limit" data-set="budgets.max_model_usd" value="${esc(settings.budgets?.max_model_usd ?? '')}">
            </div>
            <span class="hint">Ceiling per single model in a sweep</span>
          </div>

          <div class="field">
            <label for="s-confirm_above_usd">Confirmation prompt threshold</label>
            <div class="input-with-prefix">
              <span class="input-prefix font-mono">$</span>
              <input id="s-confirm_above_usd" type="number" step="0.01" min="0" data-set="budgets.confirm_above_usd" value="${esc(settings.budgets?.confirm_above_usd ?? 5.0)}">
            </div>
            <span class="hint">UI asks for confirmation if forecast exceeds this</span>
          </div>
        </div>
      </div>

      <div class="settings-card">
        <div class="settings-card-header">
          <div class="settings-card-icon">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
          </div>
          <div>
            <h3>Budget Exceeded Policy</h3>
            <p>Execution behavior when a sweep forecast or live call crosses a budget limit.</p>
          </div>
        </div>

        <div class="field" style="max-width:440px;">
          <label for="s-on_exceed">Budget exceed policy</label>
          <select id="s-on_exceed" data-set="budgets.on_exceed">
            <option value="stop" ${settings.budgets?.on_exceed === 'stop' ? 'selected' : ''}>Stop sweep immediately (Conservative — avoids excess spend)</option>
            <option value="warn" ${settings.budgets?.on_exceed === 'warn' ? 'selected' : ''}>Log budget warning and continue sweep</option>
          </select>
          <span class="hint">When stopped early, calls already completed are preserved and marked partial</span>
        </div>
      </div>`,

    storage: () => `
      <div class="settings-card">
        <div class="settings-card-header">
          <div class="settings-card-icon">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/></svg>
          </div>
          <div>
            <h3>Local SQLite Architecture</h3>
            <p>Agent Arena runs offline with zero telemetry. All benchmark data is kept 100% local.</p>
          </div>
        </div>
        <p class="small text-dim" style="margin-bottom:1rem;">
          Each evaluation stores its results in <code>&lt;project&gt;/results/arena.sqlite</code> with Write-Ahead Logging (WAL) for safe multi-process concurrency.
        </p>
        <div class="stat-pill-row">
          <div class="stat-pill"><span class="label">Storage Engine</span><span class="val font-mono">SQLite 3 (WAL)</span></div>
          <div class="stat-pill"><span class="label">Telemetry</span><span class="val font-mono">Zero External (100% Local)</span></div>
          <div class="stat-pill"><span class="label">Network Dependency</span><span class="val font-mono">None (Offline-First)</span></div>
        </div>
      </div>

      <div class="settings-card">
        <div class="settings-card-header">
          <div class="settings-card-icon" style="background:var(--warn-soft);color:var(--warn);">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
          </div>
          <div>
            <h3>Reclaim Disk Space (Vacuum)</h3>
            <p>Purge deleted runs and compact database files on disk.</p>
          </div>
        </div>
        <p class="small text-dim" style="margin-bottom:1rem;">
          When you delete runs, SQLite retains tombstones so they can be reviewed or exported. Vacuum permanently purges deleted runs and compacts database files on disk.
        </p>
        <p class="btn-row"><button class="btn btn-danger" id="s-vacuum">Vacuum all evaluation databases</button></p>
      </div>

      <div class="settings-card">
        <div class="settings-card-header">
          <div class="settings-card-icon" style="background:var(--bad-soft);color:var(--bad);">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18.36 6.64a9 9 0 1 1-12.73 0"/><line x1="12" y1="2" x2="12" y2="12"/></svg>
          </div>
          <div>
            <h3>Factory Reset</h3>
            <p>Restore global preferences to factory defaults.</p>
          </div>
        </div>
        <p class="small text-dim" style="margin-bottom:1rem;">
          Reset all user preferences, spending caps, and runner defaults back to factory settings. Project <code>config.yaml</code> files will remain untouched.
        </p>
        <p class="btn-row"><button class="btn btn-outline-danger" id="s-reset">Reset settings to defaults</button></p>
      </div>`,

    about: () => `
      <div class="about-hero">
        <div class="about-hero-header">
          <div>
            <div class="about-badge-row">
              <span class="badge-tag gold font-mono">v${esc(about.version)}</span>
              <span class="badge-tag live-tag">${esc(about.release_channel || 'Release Candidate')}</span>
              <span class="badge-tag">${esc(about.license || 'MIT Licensed')}</span>
            </div>
            <h2 style="font-size:1.6rem;margin:.5rem 0 .25rem;">Agent Arena</h2>
            <p class="lede" style="font-size:.95rem;max-width:56ch;margin-bottom:0;">
              A universal, config-driven harness for comparing LLMs on <em>your</em> real-world project.
              Structured evidence over vibes.
            </p>
          </div>
        </div>
      </div>

      <div class="about-spec-grid">
        <div class="about-spec-card">
          <span class="about-spec-label">Core Engine</span>
          <span class="about-spec-val font-mono">v${esc(about.version)}</span>
          <span class="about-spec-sub">Zero runtime dependencies</span>
        </div>
        <div class="about-spec-card">
          <span class="about-spec-label">Python Runtime</span>
          <span class="about-spec-val font-mono">Python ${esc(about.python)}</span>
          <span class="about-spec-sub">${esc(about.platform || 'macOS')}</span>
        </div>
        <div class="about-spec-card">
          <span class="about-spec-label">Cataloged Models</span>
          <span class="about-spec-val font-mono">${about.models_count || 30}+ models</span>
          <span class="about-spec-sub">Pricing as of ${esc(about.pricing_as_of || '2026-09-02')}</span>
        </div>
        <div class="about-spec-card">
          <span class="about-spec-label">Evaluation Scorers</span>
          <span class="about-spec-val font-mono">${about.scorers_count || 10} registered</span>
          <span class="about-spec-sub">Pluggable registry</span>
        </div>
        <div class="about-spec-card">
          <span class="about-spec-label">Storage Engine</span>
          <span class="about-spec-val font-mono">SQLite 3 (WAL)</span>
          <span class="about-spec-sub">Local ACID store</span>
        </div>
        <div class="about-spec-card">
          <span class="about-spec-label">Config Format</span>
          <span class="about-spec-val font-mono">${about.yaml ? 'YAML & JSON' : 'JSON (YAML optional)'}</span>
          <span class="about-spec-sub">Declarative config.yaml</span>
        </div>
      </div>

      <div class="card" style="margin-top:1.5rem;">
        <h3 style="margin-bottom:.65rem;">Key Capabilities in v2.0</h3>
        <div class="about-features-list">
          <div class="about-feature-item">
            <strong>Resumable Sweeps (<code>--resume &lt;run-id&gt;</code>)</strong>
            <p>Interrupted sweeps only re-run missing or failed calls. Never pay twice for completed benchmarks.</p>
          </div>
          <div class="about-feature-item">
            <strong>Per-Provider Rate Limiting</strong>
            <p>Token buckets for RPM, TPM, and concurrency semaphores to smoothly handle vendor throughput limits.</p>
          </div>
          <div class="about-feature-item">
            <strong>Bootstrap Statistical Resolution</strong>
            <p>Resampled paired confidence intervals on test cases. Tells you transparently when models are too close to call.</p>
          </div>
          <div class="about-feature-item">
            <strong>Evaluation Drift Watcher (<code>arena watch</code>)</strong>
            <p>Monitors model performance over time, alerting or failing CI when a model drifts or changes qualification status.</p>
          </div>
          <div class="about-feature-item">
            <strong>GitHub Action Integration</strong>
            <p>Run automated model evaluations on pull requests and post clean comparison leaderboards as comments.</p>
          </div>
          <div class="about-feature-item">
            <strong>Pricing Catalog Staleness Detection</strong>
            <p>Automatic alerts when model card pricing becomes older than 90 days.</p>
          </div>
        </div>
      </div>

      <div class="card" style="margin-top:1.25rem;">
        <h3 style="margin-bottom:.5rem;">Architecture Invariants</h3>
        <ul class="about-invariants">
          <li><strong>Stdlib-Only Core:</strong> No mandatory external Python runtime dependencies. Provider SDKs are loaded lazily on demand.</li>
          <li><strong>Zero-Dependency Browser UI:</strong> Plain HTML, CSS, and vanilla JavaScript. Zero npm packages, zero client builds.</li>
          <li><strong>Never Fabricate a Number:</strong> Honest resolution and empirical evidence over guessed numbers or vibes.</li>
          <li><strong>CLI & UI Parity:</strong> Both surfaces share the exact same <code>service/</code> layer. The UI can never disagree with the CLI.</li>
        </ul>
      </div>

      <div class="card" style="margin-top:1.25rem;">
        <h3 style="margin-bottom:.5rem;">Documentation & Community</h3>
        <p class="small text-dim" style="margin-bottom:.85rem;">
          Created and maintained by <strong>${esc(about.author || 'Aditya Mhaske')}</strong>. Released under the permissive MIT License.
        </p>
        <p class="btn-row">
          <a class="btn btn-primary" href="https://adityamhaske.github.io/agent-arena" target="_blank" rel="noopener">
            Official Documentation
          </a>
          <a class="btn" href="https://github.com/adityamhaske/agent-arena" target="_blank" rel="noopener">
            GitHub Repository
          </a>
          <a class="btn" href="https://adityamhaske.github.io/agent-arena/releases/" target="_blank" rel="noopener">
            Changelog & Releases
          </a>
          <a class="btn" href="https://adityamhaske.github.io/agent-arena/decisions/" target="_blank" rel="noopener">
            Architecture Decisions
          </a>
        </p>
      </div>`,
  };

  app().innerHTML = `
    <div class="head-row" style="margin-bottom:1.5rem;">
      <div>
        <h1 style="font-size:1.6rem;margin-bottom:0.25rem;">Settings</h1>
        <p class="lede" style="font-size:0.95rem;margin:0;">Configure global appearance, runner seeds, spend caps, and workspace directories.</p>
      </div>
    </div>
    <div class="settings-layout">
      <nav class="settings-nav" aria-label="Settings categories">
        ${tabs}
      </nav>
      <div class="settings-content-wrapper">
        <div id="settings-panel">${(panels[tab] || panels.general)()}</div>
        ${tab === 'storage' || tab === 'about' ? '' :
          `<div class="settings-footer-bar">
            <div class="settings-footer-meta">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>
              <span>Saved locally to <code>settings.json</code></span>
            </div>
            <button class="btn btn-primary btn-save" id="s-save">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>
              <span>Save changes</span>
            </button>
          </div>`}
      </div>
    </div>`;

  /* Theme cards & select inside general settings tab */
  const themeCards = app().querySelectorAll('.theme-card');
  const themeSelect = $('#s-theme');
  if (themeSelect) {
    themeSelect.value = currentTheme;
  }
  themeCards.forEach((card) => {
    card.addEventListener('click', () => {
      const chosen = card.dataset.themeVal;
      themeCards.forEach((c) => {
        const isSelected = c === card;
        c.classList.toggle('active', isSelected);
        c.setAttribute('aria-checked', String(isSelected));
      });
      if (themeSelect) {
        themeSelect.value = chosen;
      }
      try { localStorage.setItem('arena-theme', chosen); } catch { /* private mode */ }
      applyTheme(chosen);
    });
  });

  const densitySelect = $('#s-density');
  if (densitySelect) {
    densitySelect.addEventListener('change', () => {
      applyDensity(densitySelect.value);
    });
  }

  if ($('#s-save')) {
    $('#s-save').addEventListener('click', async () => {
      const saveBtn = $('#s-save');
      const originalHtml = saveBtn ? saveBtn.innerHTML : '';
      if (saveBtn) {
        saveBtn.disabled = true;
        saveBtn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="spin"><circle cx="12" cy="12" r="10"/><path d="M12 2a10 10 0 0 1 10 10"/></svg> <span>Saving…</span>`;
      }
      const patch = {};
      app().querySelectorAll('[data-set]').forEach((el) => {
        let value;
        if (el.type === 'checkbox') {
          value = el.checked;
        } else if (el.type === 'number') {
          const raw = el.value.trim();
          value = raw === '' ? null : Number(raw);
        } else {
          value = el.value.trim();
        }
        const [head, tail] = el.dataset.set.split('.');
        if (tail) {
          (patch[head] ||= { ...(state.settings[head] || {}) })[tail] = value;
        } else {
          patch[head] = value;
        }
      });
      try {
        const updated = await api('/api/settings', { method: 'PUT', body: patch });
        state.settings = updated;
        if (updated.density) applyDensity(updated.density);
        if (saveBtn) {
          saveBtn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg> <span>Saved!</span>`;
          setTimeout(() => {
            if (saveBtn) {
              saveBtn.disabled = false;
              saveBtn.innerHTML = originalHtml;
            }
          }, 1500);
        }
        toast('Settings saved successfully.');
      } catch (err) {
        if (saveBtn) {
          saveBtn.disabled = false;
          saveBtn.innerHTML = originalHtml;
        }
        toast(`Error saving settings: ${err.message}`, 'error');
      }
    });
  }

  if ($('#s-vacuum')) {
    $('#s-vacuum').addEventListener('click', async () => {
      const { projects } = await api('/api/projects');
      let removed = 0;
      for (const project of projects) {
        try {
          const plan = await api(`/api/projects/${project.name}/vacuum`, { method: 'POST' });
          removed += plan.runs_removed || 0;
        } catch { /* a project with no database yet has nothing to reclaim */ }
      }
      toast(removed ? `Permanently removed ${removed} deleted run(s).` : 'Nothing to reclaim.');
    });
  }

  if ($('#s-reset')) {
    $('#s-reset').addEventListener('click', async () => {
      if (!confirm('Reset all user settings and limits to default values? Project configs will not be changed.')) return;
      try {
        const reset = await api('/api/settings/reset', { method: 'POST' });
        state.settings = reset;
        applyDensity(reset.density || 'comfortable');
        toast('Settings restored to factory defaults.');
        await viewSettings(tab);
      } catch (err) {
        toast(`Error resetting settings: ${err.message}`, 'error');
      }
    });
  }
}

/* --------------------------------------------- view: models and scorers */

function getModelTierInfo(m) {
  const mid = (m.model || '').toLowerCase();
  const name = (m.display || '').toLowerCase();
  if (mid.includes('opus') || mid.includes('fable') || mid.includes('mythos')) {
    return { label: 'Frontier', tier: 950, cls: 'tier-frontier' };
  }
  if (mid.includes('gpt-5') && !mid.includes('mini')) {
    return { label: 'Frontier', tier: 940, cls: 'tier-frontier' };
  }
  if (mid.includes('o3') || mid.includes('o1')) {
    return { label: 'Reasoning', tier: 930, cls: 'tier-frontier' };
  }
  if (mid.includes('sonnet') || mid.includes('claude-3-5')) {
    return { label: 'Flagship', tier: 920, cls: 'tier-flagship' };
  }
  if (mid.includes('gemini-2.5-pro') || mid.includes('gemini-1.5-pro')) {
    return { label: 'Flagship', tier: 910, cls: 'tier-flagship' };
  }
  if (mid.includes('gpt-4o') && !mid.includes('mini')) {
    return { label: 'Flagship', tier: 900, cls: 'tier-flagship' };
  }
  if (mid.includes('gpt-4.1') && !mid.includes('mini')) {
    return { label: 'Flagship', tier: 890, cls: 'tier-flagship' };
  }
  if (mid.includes('mistral-large')) {
    return { label: 'Flagship', tier: 880, cls: 'tier-flagship' };
  }
  if (mid.includes('o4-mini')) {
    return { label: 'Fast Reasoning', tier: 750, cls: 'tier-flagship' };
  }
  if (mid.includes('gpt-5-mini')) {
    return { label: 'Efficiency', tier: 740, cls: '' };
  }
  if (mid.includes('gemini-2.5-flash')) {
    return { label: 'Fast / Multimodal', tier: 730, cls: '' };
  }
  if (mid.includes('haiku')) {
    return { label: 'Efficiency', tier: 720, cls: '' };
  }
  if (mid.includes('gpt-4.1-mini') || mid.includes('gpt-4o-mini')) {
    return { label: 'Efficiency', tier: 710, cls: '' };
  }
  if (mid.includes('gemini-2.0-flash') || mid.includes('gemini-1.5-flash')) {
    return { label: 'Fast', tier: 700, cls: '' };
  }
  if (mid.includes('mistral-small')) {
    return { label: 'Efficiency', tier: 680, cls: '' };
  }
  if (mid.includes('local') || mid.includes('mock')) {
    return { label: 'Local / Offline', tier: 100, cls: '' };
  }
  return { label: 'General', tier: 500, cls: '' };
}

async function viewModels() {
  crumbs({ label: 'Models' });
  const catalog = state.catalog || await api('/api/catalog');
  const rawReal = catalog.real_models || [];
  const rawDemo = catalog.demo_models || [];

  // Sort real models: Active/Ready first, then Best model capability tier first
  const real = [...rawReal].sort((a, b) => {
    const aAvail = a.available ? 1 : 0;
    const bAvail = b.available ? 1 : 0;
    if (bAvail !== aAvail) return bAvail - aAvail;

    const aTier = getModelTierInfo(a).tier;
    const bTier = getModelTierInfo(b).tier;
    if (bTier !== aTier) return bTier - aTier;

    const aOut = Number(a.output_usd_per_mtok) || 0;
    const bOut = Number(b.output_usd_per_mtok) || 0;
    if (bOut !== aOut) return bOut - aOut;

    const aCtx = Number(a.context_tokens) || 0;
    const bCtx = Number(b.context_tokens) || 0;
    if (bCtx !== aCtx) return bCtx - aCtx;

    return (a.model || '').localeCompare(b.model || '');
  });

  // Sort demo models: Best accuracy first (Frontier 96% -> Balanced 88% -> Small 78% -> Tiny 55%)
  const demo = [...rawDemo].sort((a, b) => {
    return (b.params?.accuracy ?? 0) - (a.params?.accuracy ?? 0);
  });

  const readyReal = real.filter((m) => m.available);
  const unavailableReal = real.filter((m) => !m.available);

  const renderModelRow = (m) => {
    const tier = getModelTierInfo(m);
    return `
      <tr data-provider="${esc(m.provider || '')}" data-available="${m.available ? 'true' : 'false'}" data-name="${esc(m.model)} ${esc(m.display || '')} ${esc(m.provider || '')}">
        <td>
          <div style="display:flex; align-items:center; gap:.5rem;">
            <span class="dot ${m.available ? 'ok' : 'warn'}" title="${m.available ? 'Ready to call' : 'Requires API key'}"></span>
            <div>
              <code>${esc(m.model)}</code>
              ${m.display ? `<br><span class="hint" style="font-size:.78rem">${esc(m.display)}</span>` : ''}
            </div>
          </div>
        </td>
        <td><span class="model-tier-pill ${tier.cls}">${tier.label}</span></td>
        <td><span class="pill mute">${esc(m.provider || '—')}</span></td>
        <td class="num">${m.input_usd_per_mtok != null ? '$' + Number(m.input_usd_per_mtok).toFixed(2) : '—'}</td>
        <td class="num">${m.output_usd_per_mtok != null ? '$' + Number(m.output_usd_per_mtok).toFixed(2) : '—'}</td>
        <td class="num">${m.context_tokens ? Number(m.context_tokens).toLocaleString() : '—'}</td>
        <td>${m.available
               ? '<span class="pill ok"><span class="dot ok"></span> ready</span>'
               : `<span class="pill warn"><span class="dot warn"></span> set <code>${esc(m.api_key_env || 'a key')}</code></span>`}</td>
      </tr>`;
  };

  app().innerHTML = `
    <div class="head-row">
      <div>
        <h1>Models</h1>
        <p class="lede">What the price catalog knows. A model with no sourced price gets no cost
        metric rather than a guessed one — which is why one unpriced model removes the cost
        column for the whole run.</p>
      </div>
    </div>

    <div class="model-stat-grid">
      <div class="model-stat-card">
        <span class="stat-label"><span class="dot ok"></span> Ready to Call</span>
        <span class="stat-val good">${readyReal.length}</span>
        <span class="stat-desc">Credentials present in environment</span>
      </div>
      <div class="model-stat-card">
        <span class="stat-label"><span class="dot warn"></span> Requires API Key</span>
        <span class="stat-val warn">${unavailableReal.length}</span>
        <span class="stat-desc">Set environment variable to unlock</span>
      </div>
      <div class="model-stat-card">
        <span class="stat-label"><span class="dot busy"></span> Simulated Models</span>
        <span class="stat-val">${demo.length}</span>
        <span class="stat-desc">Zero-cost baseline mocks</span>
      </div>
    </div>

    <div class="model-toolbar">
      <div class="model-filter-chips" id="model-filter-chips">
        <button class="filter-chip active" data-filter="all">All (${real.length})</button>
        <button class="filter-chip" data-filter="ready"><span class="dot ok" style="width:7px;height:7px;margin-right:4px;"></span>Ready (${readyReal.length})</button>
        <button class="filter-chip" data-filter="needs_key"><span class="dot warn" style="width:7px;height:7px;margin-right:4px;"></span>Needs Key (${unavailableReal.length})</button>
        <button class="filter-chip" data-filter="anthropic">Anthropic</button>
        <button class="filter-chip" data-filter="openai">OpenAI</button>
        <button class="filter-chip" data-filter="gemini">Gemini</button>
        <button class="filter-chip" data-filter="mistral">Mistral</button>
      </div>
      <div class="model-search-box">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="opacity:.6"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
        <input type="search" id="model-search" placeholder="Filter models by name or provider..." autocomplete="off">
      </div>
    </div>

    <div class="models-section" data-section="ready">
      <h2 style="display:flex; align-items:center; gap:.5rem;"><span class="dot ok"></span> Available & Ready Models (${readyReal.length})</h2>
      <p class="hint" style="margin-top:-.5rem; margin-bottom:.75rem;">
        Models with active credentials detected on this machine. Ready to run sweeps immediately, ordered with <strong>highest capability frontier models first</strong>.
      </p>

      ${readyReal.length ? `
        <div class="grid-scroll"><table class="data">
          <thead><tr>
            <th>model</th>
            <th>tier</th>
            <th>provider</th>
            <th class="num">in $/Mtok</th>
            <th class="num">out $/Mtok</th>
            <th class="num">context</th>
            <th>credential / status</th>
          </tr></thead>
          <tbody>${readyReal.map(renderModelRow).join('')}</tbody>
        </table></div>` : '<p class="hint">No ready models detected. Set API keys in your environment to unlock provider models.</p>'}
    </div>

    <div class="models-section" data-section="unavailable" style="margin-top:2.5rem;">
      <h2 style="display:flex; align-items:center; gap:.5rem;"><span class="dot warn"></span> Models Requiring API Keys (${unavailableReal.length})</h2>
      <p class="hint" style="margin-top:-.5rem; margin-bottom:.75rem;">
        These models are cataloged with verified list pricing. Export the corresponding environment variable to enable them.
      </p>

      ${unavailableReal.length ? `
        <div class="grid-scroll"><table class="data">
          <thead><tr>
            <th>model</th>
            <th>tier</th>
            <th>provider</th>
            <th class="num">in $/Mtok</th>
            <th class="num">out $/Mtok</th>
            <th class="num">context</th>
            <th>credential / status</th>
          </tr></thead>
          <tbody>${unavailableReal.map(renderModelRow).join('')}</tbody>
        </table></div>` : ''}
    </div>

    <div class="models-section" data-section="demo" style="margin-top:2.5rem;">
      <h2 style="display:flex; align-items:center; gap:.5rem;"><span class="dot ok"></span> Free Simulated Models (${demo.length})</h2>
      <p class="hint" style="margin-top:-.5rem; margin-bottom:.75rem;">
        Deterministic and zero-cost, ordered by <strong>best simulated accuracy</strong> first. Use these to verify scorers before spending on live providers.
      </p>
      ${demo.length ? `
        <div class="grid-scroll"><table class="data">
          <thead><tr><th>key</th><th>what it stands in for</th><th class="num">accuracy</th><th class="num">latency</th><th class="num">sim in/out $/Mtok</th></tr></thead>
          <tbody>${demo.map((m) => `
            <tr data-provider="mock" data-available="true" data-name="${esc(m.model)} ${esc(m.label || '')}">
              <td>
                <div style="display:flex; align-items:center; gap:.5rem;">
                  <span class="dot ok" title="Ready (Free)"></span>
                  <code>${esc(m.model)}</code>
                </div>
              </td>
              <td><strong>${esc(m.label || '')}</strong><br><span class="hint">${esc(m.blurb || '')}</span></td>
              <td class="num"><span class="pill ok" style="font-family:var(--mono); font-weight:700;">${m.params?.accuracy != null ? m.params.accuracy + '%' : '—'}</span></td>
              <td class="num">${m.params?.latency_ms != null ? m.params.latency_ms + 'ms' : '—'}</td>
              <td class="num">${m.card?.input_usd_per_mtok != null ? '$' + m.card.input_usd_per_mtok + ' / $' + m.card.output_usd_per_mtok : '—'}</td>
            </tr>`).join('')}</tbody>
        </table></div>` : ''}
    </div>`;

  // Interactive Live Filter & Search across all tables
  let activeFilter = 'all';
  const searchInput = document.getElementById('model-search');
  const chipContainer = document.getElementById('model-filter-chips');

  function applyFilter() {
    const query = (searchInput?.value || '').trim().toLowerCase();
    const rows = document.querySelectorAll('.models-section tbody tr');
    rows.forEach((row) => {
      const provider = (row.getAttribute('data-provider') || '').toLowerCase();
      const available = row.getAttribute('data-available') === 'true';
      const text = (row.getAttribute('data-name') || '').toLowerCase();

      let matchesFilter = true;
      if (activeFilter === 'ready') matchesFilter = available;
      else if (activeFilter === 'needs_key') matchesFilter = !available;
      else if (activeFilter !== 'all') matchesFilter = provider.includes(activeFilter);

      const matchesSearch = !query || text.includes(query) || provider.includes(query);
      row.style.display = (matchesFilter && matchesSearch) ? '' : 'none';
    });

    document.querySelectorAll('.models-section').forEach((sec) => {
      const visibleRows = sec.querySelectorAll('tbody tr:not([style*="display: none"])');
      sec.style.display = visibleRows.length ? '' : 'none';
    });
  }

  if (chipContainer) {
    chipContainer.addEventListener('click', (e) => {
      const btn = e.target.closest('.filter-chip');
      if (!btn) return;
      chipContainer.querySelectorAll('.filter-chip').forEach((c) => c.classList.remove('active'));
      btn.classList.add('active');
      activeFilter = btn.getAttribute('data-filter') || 'all';
      applyFilter();
    });
  }

  if (searchInput) {
    searchInput.addEventListener('input', applyFilter);
  }
}

async function viewScorers() {
  crumbs({ label: 'Scorers' });
  const catalog = state.catalog || await api('/api/catalog');
  const scorers = catalog.scorers || [];

  const GUIDE = {
    classification: {
      ref: 'billing',
      use: 'One of a fixed set of predefined category labels.',
      fails: 'Two labels where one contains the other, or a model that outputs verbose reasoning instead of a bare label.',
      exec: 'Native Stdlib (0ms)',
      scoring: 'Strict label match (0 or 1)',
    },
    exact_match: {
      ref: 'refund issued',
      use: 'Short deterministic string with strict equality check.',
      fails: 'The model adds a polite preamble or punctuation. Strip it in a hook, or use contains.',
      exec: 'Native Stdlib (0ms)',
      scoring: 'Exact binary match (0 or 1)',
    },
    contains: {
      ref: '["order id", "refund"]',
      use: 'The answer must mention essential keywords or substrings.',
      fails: 'Cannot distinguish an assertion from a negation (e.g., "does not include a refund" still passes).',
      exec: 'Native Stdlib (0ms)',
      scoring: 'Keyword substring matching',
    },
    regex: {
      ref: '^ORD-\\d{6}$',
      use: 'Structured pattern extraction: ticket IDs, dates, codes, SKUs.',
      fails: 'Anchored too tightly. Models vary the text around the token far more than the pattern itself.',
      exec: 'Python re engine',
      scoring: 'Regex expression match',
    },
    numeric: {
      ref: '42.5 ± 0.05',
      use: 'Numbers, percentages, financial calculations with relative tolerance.',
      fails: 'Multiple numbers in output and the target quantity is not parsed first.',
      exec: 'Float parser & epsilon diff',
      scoring: 'Value tolerance interval',
    },
    json_match: {
      ref: '{"total": 12.5, "currency": "USD"}',
      use: 'Structured JSON objects. Grants partial credit per matching key.',
      fails: 'The model wraps JSON in markdown fences (```json...```) — strip in post_process.',
      exec: 'JSON parser & key comparator',
      scoring: 'Partial credit per valid key (0.0 – 1.0)',
    },
    semantic: {
      ref: 'the customer was charged twice',
      use: 'Natural language where phrasing varies but underlying meaning must match.',
      fails: 'Lexical similarity can reward shared keywords rather than true semantic equivalence.',
      exec: 'Token similarity algorithm',
      scoring: 'Cosine / token overlap similarity',
    },
    code_exec: {
      ref: 'assert solve([1,2]) == 3',
      use: 'Generated Python code, executed against unit test assertions.',
      fails: 'Runs in local subprocess isolation (not an unmetered sandbox). Do not use with untrusted code.',
      exec: 'Subprocess runner with timeout',
      scoring: 'Assertion pass rate (0.0 – 1.0)',
    },
    llm_judge: {
      ref: 'Rubric with evaluation criteria',
      use: 'Nuanced quality, tone, style, or adherence to complex guidelines.',
      fails: 'Incurs additional API latency & cost per test case, and couples evaluation to judge reliability.',
      exec: 'LLM API Call ($ + latency)',
      scoring: 'Graded rubric (0.0 – 1.0)',
    },
    manual: {
      ref: 'Human inspection queue',
      use: 'Collect real model outputs for human grading before automating with heuristics.',
      fails: 'Always assigns fixed score (0.5) to avoid biasing unreviewed sweeps.',
      exec: 'Interactive review queue',
      scoring: 'Human reviewer score',
    },
  };

  app().innerHTML = `
    <div class="head-row">
      <div>
        <h1>Evaluation Scorers</h1>
        <p class="lede">How model responses are graded. Choose the evaluation method that matches the exact shape of your expected outputs — wrong scorers produce misleading rankings.</p>
      </div>
      <div>
        <span class="badge-tag"><strong>${scorers.length}</strong> available scorers</span>
      </div>
    </div>

    <div class="scorer-grid">${scorers.map((sc) => {
      const name = sc.name || String(sc);
      const guide = GUIDE[name] || {};
      return `
        <div class="scorer-card">
          <div class="scorer-card-head">
            <code>${esc(name)}</code>
            <span class="pill ${sc.source === 'builtin' ? 'mute' : 'ok'}">${esc(sc.source || 'builtin')}</span>
          </div>

          <p class="scorer-card-desc">${esc(sc.description || guide.use || '')}</p>

          <div class="scorer-box-section">
            <span class="scorer-box-label">Best Used For</span>
            <div class="scorer-box-value">${esc(guide.use || 'Deterministic comparison')}</div>
          </div>

          <div class="scorer-box-section">
            <span class="scorer-box-label">Expected Reference Format</span>
            <div class="scorer-ref-box"><code>${esc(guide.ref || '—')}</code></div>
          </div>

          <div class="scorer-hover-details">
            <div class="scorer-pitfall">
              <strong><span>⚠️</span> Where it breaks / Caveat</strong>
              ${esc(guide.fails || 'Ensure proper input format.')}
            </div>
            <div class="scorer-meta-row">
              <span>⚡ ${esc(guide.exec || 'Stdlib')}</span>
              <span>🎯 ${esc(guide.scoring || 'Score: 0.0 - 1.0')}</span>
            </div>
          </div>
        </div>`;
    }).join('')}</div>

    <div class="callout" style="margin-top:1.75rem">
      <div class="callout-title">Custom Project Scorers</div>
      <p class="mb0"><strong>Need custom grading logic?</strong> Drop any <code>.py</code> file in your project's
      <code>scorers/</code> directory and Agent Arena detects it automatically with zero registration boilerplate.
      Custom scorers can emit domain-specific metrics that instantly appear on the evaluation leaderboard.</p>
    </div>`;
}

/* ---------------------------------------------------------------- boot */

/* Light is the default. An explicit choice is remembered and stamped on the
 * root so it beats prefers-color-scheme either way; with no choice stored we
 * leave the attribute off and follow the OS. */
function applyTheme(theme) {
  if (theme === 'light' || theme === 'dark') {
    document.documentElement.setAttribute('data-theme', theme);
  } else {
    document.documentElement.removeAttribute('data-theme');
  }
  const dark = theme === 'dark'
    || (theme !== 'light' && matchMedia('(prefers-color-scheme: dark)').matches);
  $('#theme-toggle').innerHTML = icon(dark ? 'sun' : 'moon', {
    title: dark ? 'Switch to light' : 'Switch to dark',
  });
}

function storedTheme() {
  try { return localStorage.getItem('arena-theme') || 'system'; } catch { return 'system'; }
}

function applyDensity(density) {
  if (density === 'compact') {
    document.documentElement.setAttribute('data-density', 'compact');
  } else {
    document.documentElement.removeAttribute('data-density');
  }
}

window.addEventListener('hashchange', router);

$('#theme-toggle').addEventListener('click', () => {
  const now = document.documentElement.getAttribute('data-theme')
    || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  const next = now === 'dark' ? 'light' : 'dark';
  try { localStorage.setItem('arena-theme', next); } catch { /* private mode */ }
  applyTheme(next);
});

$('#nav-toggle').addEventListener('click', () => {
  const nav = $('#sidenav');
  const open = nav.classList.toggle('open');
  $('#nav-toggle').setAttribute('aria-expanded', String(open));
});

$('#modal').addEventListener('click', (event) => { if (event.target.id === 'modal') closeModal(); });
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && !$('#modal').hidden) closeModal();
});

(async function start() {
  applyTheme(storedTheme());
  $('#nav-toggle').innerHTML = icon('menu', { title: 'Menu' });

  /* Anything pointing off this origin opens in a new tab, so a click never
   * throws away an evaluation in progress. Delegated, so it covers markup
   * every view renders without each one remembering to set it. */
  document.addEventListener('click', (event) => {
    const link = event.target.closest?.('a[href^="http"]');
    if (link && link.host !== location.host) {
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
    }
  }, true);

  try {
    const [catalog, settings] = await Promise.all([
      api('/api/catalog'),
      api('/api/settings').catch(() => null),
    ]);
    state.catalog = catalog;
    if (settings) {
      state.settings = settings;
      applyDensity(settings.density);
    }
  } catch (error) {
    app().innerHTML = `<div class="card"><h2>Cannot reach the server</h2><p>${esc(error.message)}</p></div>`;
    return;
  }
  router();
})();
