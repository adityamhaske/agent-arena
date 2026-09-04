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

/* The sidenav. `match` decides which entry is highlighted for a given hash —
 * a prefix test rather than equality, so /p/foo/results still lights up
 * "Projects" instead of leaving the user with no sense of where they are. */
const NAV = [
  { group: 'Evaluate' },
  { href: '#/', icon: '◎', label: 'Overview', match: (p) => p === '/' },
  { href: '#/projects', icon: '▤', label: 'Projects', match: (p) => p === '/projects' || p.startsWith('/p/') },
  { href: '#/runs', icon: '≡', label: 'Runs', match: (p) => p === '/runs' },
  { group: 'Reference' },
  { href: '#/models', icon: '◈', label: 'Models', match: (p) => p === '/models' },
  { href: '#/scorers', icon: '✓', label: 'Scorers', match: (p) => p === '/scorers' },
  { href: '#/providers', icon: '⇄', label: 'Providers', match: (p) => p === '/providers' },
  { group: 'Configure' },
  { href: '#/settings', icon: '⚙', label: 'Settings', match: (p) => p.startsWith('/settings') },
];

function renderNav(path) {
  $('#nav').innerHTML = NAV.map((item) => (
    item.group
      ? `<p class="nav-group">${esc(item.group)}</p>`
      : `<a href="${item.href}" data-link class="${item.match(path) ? 'on' : ''}">
           <span class="ico" aria-hidden="true">${item.icon}</span>${esc(item.label)}</a>`
  )).join('');
}

function crumbs(...parts) {
  $('#crumbs').innerHTML = parts.map((part, i) => {
    const last = i === parts.length - 1;
    const node = part.href && !last
      ? `<a href="${part.href}" data-link>${esc(part.label)}</a>`
      : `<span class="${last ? 'here' : ''}">${esc(part.label)}</span>`;
    return i ? `<span class="sep">/</span>${node}` : node;
  }).join('');
}

async function router() {
  if (state.poll) { clearInterval(state.poll); state.poll = null; }
  const path = location.hash.replace(/^#/, '') || '/';
  renderNav(path);
  $('#sidenav').classList.remove('open');
  $('#nav-toggle').setAttribute('aria-expanded', 'false');
  for (const [pattern, view] of routes) {
    const match = path.match(pattern);
    if (match) {
      app().innerHTML = '<div class="loading">Loading…</div>';
      try {
        await view(...match.slice(1));
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
      <div class="eyebrow">New evaluation</div>
      <h1>${esc(WIZARD_STEPS[d.step])}</h1>
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
    const demo = state.catalog.demo_models.map((m) => `
      <button class="choice" data-model="${esc(m.key)}" aria-pressed="${d.models.includes(m.key)}">
        <strong>${esc(m.label)}</strong>
        <span>${esc(m.blurb)}</span>
      </button>`).join('');
    const real = state.catalog.real_models.map((m) => `
      <button class="choice" data-model="${esc(m.model)}" aria-pressed="${d.models.includes(m.model)}"
              ${m.available ? '' : 'disabled title="Needs an API key that is not set on this machine"'}>
        <strong>${esc(m.display)}</strong>
        <span>${esc(m.provider)} · $${esc(m.input_usd_per_mtok ?? '?')} in / $${esc(m.output_usd_per_mtok ?? '?')} out per million words-ish</span>
        <em>${m.available ? 'Ready to use' : `Needs ${esc(m.api_key_env)} — not set`}</em>
      </button>`).join('');
    return `
      <h3>Free simulated models</h3>
      <p class="hint">Stand-ins with fixed accuracy, speed and price. They cost nothing and let you
      see exactly how this works before spending anything. Recommended for your first run.</p>
      <div class="choices">${demo}</div>
      <h3 style="margin-top:1.5rem">Real models</h3>
      <p class="hint">These make real API calls and cost real money. Greyed-out ones need an API key
      set on this computer.</p>
      <div class="choices">${real}</div>`;
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
              <td><textarea data-test="${i}" data-key="input" placeholder="I was charged twice this month.">${esc(t.input)}</textarea></td>
              <td><textarea data-test="${i}" data-key="reference" placeholder="${esc(preset?.answer_hint || '')}">${esc(t.reference)}</textarea></td>
              <td><button class="btn btn-sm" data-act="drop-test" data-i="${i}" aria-label="Remove example">✕</button></td>
            </tr>`).join('')}
        </tbody>
      </table>
    </div>
    <div class="btn-row" style="margin-top:.8rem">
      <button class="btn btn-sm" data-act="add-test">Add an example</button>
      <button class="btn btn-sm" data-act="paste-tests">Paste a list</button>
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

async function viewProject(name) {
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
        : m.ready ? '<span class="pill good">ready</span>'
        : `<span class="pill warn">needs a key</span>`}
    </li>`).join('');

  app().innerHTML = `
    <div class="page-head">
      <div class="eyebrow">Evaluation</div>
      <h1>${esc(p.project)}</h1>
      <p class="lede">${esc(p.description || 'No description.')}</p>
    </div>

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
}

/* ------------------------------------------------------------ view: run */

async function viewRun(name) {
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
    return `<div class="${cls}">${esc(r.model)} · ${esc(r.test)} — ${esc(body.slice(0, 110))}</div>`;
  }).join('');

  app().innerHTML = `
    <div class="page-head">
      <div class="eyebrow">Running</div>
      <h1>${esc(name)}</h1>
    </div>
    ${job.status === 'error' ? `
      <div class="card">
        <div class="callout bad"><p class="mb0"><strong>The run stopped.</strong> ${esc(job.error)}</p></div>
        ${job.error_detail ? `<details><summary>Technical detail</summary><pre>${esc(job.error_detail)}</pre></details>` : ''}
        <p class="btn-row"><a class="btn" href="#/p/${esc(name)}" data-link>Back to the evaluation</a></p>
      </div>` : `
      <div class="card">
        <p><strong>${job.completed.toLocaleString()}</strong> of
           <strong>${(job.planned || 0).toLocaleString()}</strong> calls done
           ${job.eta_s != null ? `· about ${Math.ceil(job.eta_s)}s left` : ''}</p>
        <div class="progress"><i style="width:${percent}%"></i></div>
        <p class="small muted">Every answer is graded as it arrives. You can leave this page —
        the run keeps going.</p>
        ${feed ? `<div class="feed">${feed}</div>` : ''}
      </div>`}`;
}

/* -------------------------------------------------------- view: results */

async function viewResults(name) {
  const result = state.result?.project && state.result.run_id
    ? state.result
    : await api(`/api/projects/${name}/result`);
  state.result = result;
  renderResults(name, result);
}

function renderResults(name, result) {
  const v = result.verdict;
  const ranked = result.rows.filter((r) => r.status === 'ranked');
  const out = result.rows.filter((r) => r.status !== 'ranked');
  const maxAccuracy = Math.max(...result.rows.map((r) => r.accuracy || 0), 0.0001);

  const row = (r, i) => `
    <tr class="${r.status === 'ranked' && i === 0 ? 'is-winner' : ''} ${r.status !== 'ranked' ? 'is-out' : ''}">
      <td class="num">${r.status === 'ranked' ? (i + 1) : '—'}</td>
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
    <div class="page-head">
      <div class="eyebrow">${result.hypothetical ? 'What-if — nothing was re-run' : 'Result'}</div>
      <h1>${esc(name)}</h1>
    </div>

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
      <h2>Every model, side by side</h2>
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
        “Overall” blends the three columns using your priorities. It is only comparable
        within this table.
      </p>
    </div>

    <div class="card">
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
        <button class="btn" data-act="whatif" data-name="${esc(name)}">Recalculate</button>
        ${result.hypothetical ? `<a class="btn" href="#/p/${esc(name)}/results" data-link data-reset="1">Back to the real result</a>` : ''}
      </div>
    </div>

    ${result.notes?.length ? `
      <div class="card">
        <h2>Worth knowing</h2>
        <ul class="muted">${result.notes.map((n) => `<li>${esc(n)}</li>`).join('')}</ul>
      </div>` : ''}

    <div class="card">
      <div class="stat-row">
        ${result.totals.calls ? `<div class="stat"><div class="k">Calls made</div><div class="v">${result.totals.calls.toLocaleString()}</div></div>` : ''}
        ${result.totals.cost_usd != null ? `<div class="stat"><div class="k">Spent</div><div class="v">$${result.totals.cost_usd.toFixed(4)}</div></div>` : ''}
        ${result.totals.duration_s ? `<div class="stat"><div class="k">Took</div><div class="v">${result.totals.duration_s}s</div></div>` : ''}
        ${result.totals.errors != null ? `<div class="stat"><div class="k">Errors</div><div class="v">${result.totals.errors}</div></div>` : ''}
      </div>
      <div class="btn-row" style="margin-top:1rem">
        <a class="btn" href="#/p/${esc(name)}" data-link>Back to the evaluation</a>
        <a class="btn" href="#/p/${esc(name)}/history" data-link>Compare with past runs</a>
      </div>
    </div>`;
}

/* ----------------------------------------------------- view: priorities */

async function viewPriorities(name) {
  const p = state.project?.name === name ? state.project : await api(`/api/projects/${name}`);
  state.project = p;
  const weights = p.weights;

  app().innerHTML = `
    <div class="page-head">
      <div class="eyebrow">${esc(p.project)}</div>
      <h1>What matters to you</h1>
      <p class="lede">This is the only thing that decides who wins. Two teams running the same
      models on the same examples can correctly reach opposite conclusions here.</p>
    </div>
    <div class="card">
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
      <p class="hint">Break one of these and a model is ruled out, not just ranked lower.
      Leave blank for no limit.</p>
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
      <button class="btn btn-primary" data-act="save-priorities" data-name="${esc(name)}">Save</button>
      <a class="btn" href="#/p/${esc(name)}" data-link>Cancel</a>
    </div>`;

  state.draft = { weights: { ...weights } };
}

/* ------------------------------------------------------- view: examples */

async function viewExamples(name) {
  const p = state.project?.name === name ? state.project : await api(`/api/projects/${name}`);
  state.project = p;
  state.draft = { tests: p.tests.map((t) => ({ ...t, reference: t.reference ?? '' })) };

  const answerLabel = p.preset?.answer_label || 'Expected answer';
  app().innerHTML = `
    <div class="page-head">
      <div class="eyebrow">${esc(p.project)}</div>
      <h1>Your examples</h1>
      <p class="lede">These are what every model gets marked against. Add the cases you actually
      worry about — the ambiguous ones tell you far more than the easy ones.</p>
    </div>
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
  const history = await api(`/api/projects/${name}/history`);
  const rows = history.runs.map((r) => `
    <tr>
      <td>${esc(timeAgo(r.started_at))}</td>
      <td><strong>${esc(r.winner || '—')}</strong></td>
      <td class="num">${r.n_results ?? '—'}</td>
      <td class="num">${r.total_cost_usd != null ? '$' + Number(r.total_cost_usd).toFixed(4) : '—'}</td>
      <td>${r.status === 'complete' ? '<span class="pill good">complete</span>' : `<span class="pill warn">${esc(r.status)}</span>`}</td>
      <td class="right"><a class="btn btn-sm" href="#/p/${esc(name)}/results?run=${esc(r.run_id)}" data-run="${esc(r.run_id)}" data-name="${esc(name)}">View</a></td>
    </tr>`).join('');

  app().innerHTML = `
    <div class="page-head">
      <div class="eyebrow">${esc(name)}</div>
      <h1>Past runs</h1>
      <p class="lede">Models change under you. Re-running the same evaluation after a provider
      update is how you catch a quality drop before your users do.</p>
    </div>
    ${history.runs.length ? `
      <div class="card">
        <div class="table-wrap">
          <table>
            <thead><tr><th>When</th><th>Winner</th><th class="num">Calls</th><th class="num">Cost</th><th>Status</th><th></th></tr></thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
      </div>
      ${renderTrend(history.models)}` : '<div class="empty"><p>No runs yet.</p></div>'}
    <p class="btn-row"><a class="btn" href="#/p/${esc(name)}" data-link>Back to the evaluation</a></p>`;
}

/** Accuracy over time, drawn as inline SVG so there is no chart library to load. */
function renderTrend(series) {
  const models = Object.entries(series).filter(([, points]) => points.length > 1);
  if (!models.length) return '';
  const width = 640, height = 200, pad = 30;
  const colors = ['#2b5cdb', '#147a45', '#9a6400', '#b3261e', '#7a3fc9'];
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

  app().innerHTML = `
    <h1>Overview</h1>
    <p class="lede">Every evaluation answers one question: <em>for this job, which AI model
    should we actually use?</em></p>

    <div class="stat-row">
      <div class="card stat"><span class="v">${projects.length}</span><span class="k">evaluation${projects.length === 1 ? '' : 's'}</span></div>
      <div class="card stat"><span class="v">${withRuns.length}</span><span class="k">have been run</span></div>
      <div class="card stat"><span class="v">${spend ? '$' + spend.toFixed(4) : '$0'}</span><span class="k">spent, last run of each</span></div>
    </div>

    <h2>Recent results</h2>
    ${withRuns.length ? `
      <div class="grid-scroll"><table class="data">
        <thead><tr><th>evaluation</th><th>winner</th><th>when</th><th class="num">cost</th><th></th></tr></thead>
        <tbody>${withRuns.map((p) => `
          <tr>
            <td><a href="#/p/${esc(p.name)}" data-link>${esc(p.name)}</a></td>
            <td>${esc(p.last_run.winner || '—')}</td>
            <td>${esc(timeAgo(p.last_run.started_at))}</td>
            <td class="num">${p.last_run.total_cost_usd != null ? '$' + Number(p.last_run.total_cost_usd).toFixed(4) : '—'}</td>
            <td><a class="btn btn-sm" href="#/p/${esc(p.name)}/results" data-link>View</a></td>
          </tr>`).join('')}</tbody>
      </table></div>`
      : `<div class="empty">
           <h2>Nothing has been run yet</h2>
           <p>The example evaluations work offline with no API key — a good first run.</p>
           <p class="btn-row"><a class="btn btn-primary" href="#/projects" data-link>See the evaluations</a></p>
         </div>`}`;
}

/* ------------------------------------------------------- view: projects */

async function viewProjects() {
  crumbs({ label: 'Projects' });
  const { projects } = await api('/api/projects?all=1');
  state.projects = projects;

  app().innerHTML = `
    <div class="head-row">
      <h1>Projects</h1>
      <a class="btn btn-primary" href="#/new" data-link>New evaluation</a>
    </div>
    ${projects.length ? `
      <div class="grid-scroll"><table class="data">
        <thead><tr><th>name</th><th>models</th><th>examples</th><th>last run</th><th>status</th><th></th></tr></thead>
        <tbody>${projects.map((p) => `
          <tr class="${p.archived ? 'is-gone' : ''}">
            <td><a href="#/p/${esc(p.name)}" data-link><strong>${esc(p.name)}</strong></a>
                <br><span class="hint">${esc((p.description || '').slice(0, 90))}</span></td>
            <td class="num">${p.models}</td>
            <td class="num">${p.tests}</td>
            <td>${p.last_run ? esc(timeAgo(p.last_run.started_at)) : '<span class="hint">never</span>'}</td>
            <td>${p.archived ? '<span class="pill mute">archived</span>' : '<span class="pill ok">active</span>'}</td>
            <td class="row-actions">
              <button class="btn btn-sm" data-dup="${esc(p.name)}">Duplicate</button>
              <button class="btn btn-sm" data-arch="${esc(p.name)}" data-on="${p.archived ? '0' : '1'}">${p.archived ? 'Unarchive' : 'Archive'}</button>
              <button class="btn btn-sm btn-danger" data-del="${esc(p.name)}">Delete</button>
            </td>
          </tr>`).join('')}</tbody>
      </table></div>`
      : `<div class="empty"><h2>No evaluations yet</h2>
           <p class="btn-row"><a class="btn btn-primary" href="#/new" data-link>Create one</a></p></div>`}`;

  app().querySelectorAll('[data-dup]').forEach((b) => b.addEventListener('click', () => duplicateProject(b.dataset.dup)));
  app().querySelectorAll('[data-arch]').forEach((b) => b.addEventListener('click', () => archiveProject(b.dataset.arch, b.dataset.on === '1')));
  app().querySelectorAll('[data-del]').forEach((b) => b.addEventListener('click', () => deleteProject(b.dataset.del)));
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

  app().innerHTML = `
    <h1>Runs</h1>
    <p class="lede">Every run across every evaluation, newest first.</p>
    ${runs.length ? `
      <div class="grid-scroll"><table class="data">
        <thead><tr><th>when</th><th>evaluation</th><th>winner</th><th class="num">calls</th><th class="num">cost</th><th></th></tr></thead>
        <tbody>${runs.map((r) => `
          <tr>
            <td>${esc(timeAgo(r.started_at))}${r.label ? `<br><span class="hint">${esc(r.label)}</span>` : ''}</td>
            <td><a href="#/p/${esc(r.project_name)}" data-link>${esc(r.project_name)}</a></td>
            <td>${esc(r.winner || '—')}</td>
            <td class="num">${r.n_results ?? '—'}</td>
            <td class="num">${r.total_cost_usd != null ? '$' + Number(r.total_cost_usd).toFixed(4) : '—'}</td>
            <td class="row-actions">
              <a class="btn btn-sm" href="#/p/${esc(r.project_name)}/cases/${esc(r.run_id)}" data-link>Cases</a>
              <button class="btn btn-sm btn-danger" data-rmrun="${esc(r.run_id)}" data-proj="${esc(r.project_name)}">Delete</button>
            </td>
          </tr>`).join('')}</tbody>
      </table></div>`
      : '<div class="empty"><h2>No runs yet</h2></div>'}`;

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
  const { providers } = await api('/api/providers');

  app().innerHTML = `
    <h1>Providers</h1>
    <p class="lede">A profile is a named connection: an endpoint, a credential, and any
    headers it needs. Two profiles can use the same vendor with different keys — that is
    the whole reason they exist.</p>

    ${providers.length ? `
      <div class="grid-scroll"><table class="data">
        <thead><tr><th>id</th><th>kind</th><th>endpoint</th><th>credential</th><th></th></tr></thead>
        <tbody>${providers.map((p) => `
          <tr>
            <td><strong>${esc(p.id)}</strong></td>
            <td>${esc(p.kind)}</td>
            <td>${esc(p.base_url || 'vendor default')}</td>
            <td><code>${esc(p.api_key_ref || 'conventional env var')}</code></td>
            <td class="row-actions">
              <button class="btn btn-sm" data-test="${esc(p.id)}">Test</button>
              <button class="btn btn-sm btn-danger" data-rmprov="${esc(p.id)}">Remove</button>
            </td>
          </tr>`).join('')}</tbody>
      </table></div>`
      : '<p class="hint">No profiles yet. Models fall back to the vendor\'s conventional environment variable.</p>'}

    <h2>Add a profile</h2>
    <div class="card">
      <div class="field"><label for="p-id">Name</label>
        <input id="p-id" placeholder="work_openai"></div>
      <div class="field"><label for="p-kind">Kind</label>
        <select id="p-kind">
          <option>openai</option><option>anthropic</option><option>gemini</option>
          <option>openai_compatible</option><option>local</option><option>litellm</option>
        </select></div>
      <div class="field"><label for="p-url">Endpoint <span class="hint">optional</span></label>
        <input id="p-url" placeholder="https://gateway.internal/v1"></div>
      <div class="field">
        <label for="p-key">Credential</label>
        <input id="p-key" placeholder="\${env:OPENAI_API_KEY}">
        <span class="hint">A reference is stored as written. A literal key is moved into
        your OS keyring and only the reference is saved to disk.</span>
      </div>
      <p class="btn-row"><button class="btn btn-primary" id="p-save">Save profile</button></p>
    </div>`;

  app().querySelectorAll('[data-test]').forEach((b) => b.addEventListener('click', async () => {
    b.disabled = true; b.textContent = 'Testing…';
    try {
      const report = await api(`/api/providers/${b.dataset.test}/test`, { method: 'POST' });
      toast(report.ok ? `Reachable in ${report.latency_ms}ms.` : `Unreachable — ${report.error || report.status}`, !report.ok);
    } finally { b.disabled = false; b.textContent = 'Test'; }
  }));

  app().querySelectorAll('[data-rmprov]').forEach((b) => b.addEventListener('click', async () => {
    const id = b.dataset.rmprov;
    const plan = await api(`/api/providers/${id}?dry_run=1`, { method: 'DELETE' });
    await confirmDestructive({
      title: `Remove provider ${id}?`,
      plan,
      danger: 'Remove',
      commit: async () => {
        await api(`/api/providers/${id}?purge_key=1`, { method: 'DELETE' });
        toast(`Removed ${id} and its stored credential.`);
        router();
      },
    });
  }));

  $('#p-save').addEventListener('click', async () => {
    const body = {
      id: $('#p-id').value.trim(),
      kind: $('#p-kind').value,
      base_url: $('#p-url').value.trim() || null,
      api_key: $('#p-key').value.trim() || null,
    };
    if (!body.id) { toast('Give the profile a name.', true); return; }
    await api('/api/providers', { method: 'POST', body });
    toast(`Saved ${body.id}.`);
    router();
  });
}

/* ------------------------------------------------------- view: settings */

const SETTINGS_TABS = [
  ['general', 'General'],
  ['defaults', 'Defaults'],
  ['budgets', 'Budgets & safety'],
  ['storage', 'Storage'],
  ['about', 'About'],
];

async function viewSettings(tab = 'general') {
  crumbs({ label: 'Settings' });
  const settings = await api('/api/settings');
  state.settings = settings;

  const tabs = SETTINGS_TABS.map(([slug, label]) =>
    `<a href="#/settings/${slug}" data-link class="${slug === tab ? 'on' : ''}">${esc(label)}</a>`).join('');

  const panels = {
    general: () => `
      <div class="field"><label for="s-theme">Theme</label>
        <select id="s-theme" data-set="theme">
          ${['system', 'light', 'dark'].map((t) =>
            `<option ${settings.theme === t ? 'selected' : ''}>${t}</option>`).join('')}
        </select></div>
      <div class="field"><label for="s-dir">Projects folder</label>
        <input id="s-dir" data-set="projects_dir" value="${esc(settings.projects_dir || '')}">
        <span class="hint">Where <code>arena ui</code> looks for evaluations.</span></div>`,

    defaults: () => `
      <p class="hint">Applied to new evaluations. An existing one keeps whatever its own config says.</p>
      ${[['trials', 'Repeats per case'], ['concurrency', 'Calls in parallel'],
         ['timeout_s', 'Timeout (seconds)'], ['retries', 'Retries']].map(([key, label]) => `
        <div class="field"><label for="s-${key}">${esc(label)}</label>
          <input id="s-${key}" type="number" data-set="${key}" value="${esc(settings[key] ?? '')}"></div>`).join('')}`,

    budgets: () => `
      <p class="hint">A cap stops the sweep mid-flight and keeps whatever it already
      collected, labelled as partial. Leave blank for no cap.</p>
      ${[['max_run_usd', 'Stop a run above ($)'], ['max_model_usd', 'Stop one model above ($)'],
         ['confirm_above_usd', 'Ask before starting above ($)']].map(([key, label]) => `
        <div class="field"><label for="s-${key}">${esc(label)}</label>
          <input id="s-${key}" type="number" step="0.01" data-set="budgets.${key}"
                 value="${esc(settings.budgets?.[key] ?? '')}"></div>`).join('')}`,

    storage: () => `
      <p class="hint">Every call is written to a SQLite database beside each evaluation.
      Deleted runs stay recoverable until a vacuum removes them for good.</p>
      <div class="card">
        <p><strong>Reclaim space</strong></p>
        <p class="hint">Permanently removes runs you have already deleted, in every evaluation.</p>
        <p class="btn-row"><button class="btn btn-danger" id="s-vacuum">Vacuum all evaluations</button></p>
      </div>`,

    about: () => `
      <div class="card">
        <p><strong>Agent Arena</strong> <span id="about-version" class="hint"></span></p>
        <p class="hint">Structured evidence over vibes. The browser and the command line
        share one engine, so they can never disagree about who won.</p>
        <p class="btn-row">
          <a class="btn" href="https://adityamhaske.github.io/agent-arena" target="_blank" rel="noopener">Documentation</a>
          <a class="btn" href="https://github.com/adityamhaske/agent-arena" target="_blank" rel="noopener">Source</a>
        </p>
      </div>`,
  };

  app().innerHTML = `
    <h1>Settings</h1>
    <div class="settings-tabs">${tabs}</div>
    <div id="settings-panel">${(panels[tab] || panels.general)()}</div>
    ${tab === 'storage' || tab === 'about' ? '' :
      '<p class="btn-row"><button class="btn btn-primary" id="s-save">Save</button></p>'}`;

  if ($('#about-version')) $('#about-version').textContent = state.version ? `v${state.version}` : '';

  if ($('#s-save')) {
    $('#s-save').addEventListener('click', async () => {
      const patch = {};
      app().querySelectorAll('[data-set]').forEach((el) => {
        const raw = el.value.trim();
        const value = el.type === 'number' ? (raw === '' ? null : Number(raw)) : raw;
        const [head, tail] = el.dataset.set.split('.');
        if (tail) { (patch[head] ||= { ...(state.settings[head] || {}) })[tail] = value; }
        else { patch[head] = value; }
      });
      await api('/api/settings', { method: 'PUT', body: patch });
      toast('Saved.');
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
}

/* --------------------------------------------- view: models and scorers */

async function viewModels() {
  crumbs({ label: 'Models' });
  const catalog = state.catalog || await api('/api/catalog');
  const real = catalog.real_models || [];
  const demo = catalog.demo_models || [];

  app().innerHTML = `
    <h1>Models</h1>
    <p class="lede">What the price catalog knows. A model with no sourced price gets no cost
    metric rather than a guessed one — which is why one unpriced model removes the cost
    column for the whole run.</p>

    <h2>Real models</h2>
    ${real.length ? `
      <div class="grid-scroll"><table class="data">
        <thead><tr><th>model</th><th>provider</th><th class="num">in $/Mtok</th>
          <th class="num">out $/Mtok</th><th class="num">context</th><th>credential</th></tr></thead>
        <tbody>${real.map((m) => `
          <tr>
            <td><code>${esc(m.model)}</code>${m.display ? `<br><span class="hint">${esc(m.display)}</span>` : ''}</td>
            <td>${esc(m.provider || '—')}</td>
            <td class="num">${m.input_usd_per_mtok ?? '—'}</td>
            <td class="num">${m.output_usd_per_mtok ?? '—'}</td>
            <td class="num">${m.context_tokens ? Number(m.context_tokens).toLocaleString() : '—'}</td>
            <td>${m.available
                   ? '<span class="pill ok">ready</span>'
                   : `<span class="pill warn">set ${esc(m.api_key_env || 'a key')}</span>`}</td>
          </tr>`).join('')}</tbody>
      </table></div>` : '<p class="hint">No catalog entries returned.</p>'}

    <h2>Simulated models</h2>
    <p class="hint">Deterministic and free. Use these to prove your scorers and weights
    behave before spending anything on a real provider.</p>
    ${demo.length ? `
      <div class="grid-scroll"><table class="data">
        <thead><tr><th>key</th><th>what it stands in for</th><th class="num">accuracy</th><th class="num">latency</th></tr></thead>
        <tbody>${demo.map((m) => `
          <tr>
            <td><code>${esc(m.model)}</code></td>
            <td>${esc(m.blurb || m.label || '')}</td>
            <td class="num">${m.params?.accuracy != null ? m.params.accuracy + '%' : '—'}</td>
            <td class="num">${m.params?.latency_ms != null ? m.params.latency_ms + 'ms' : '—'}</td>
          </tr>`).join('')}</tbody>
      </table></div>` : ''}`;
}

async function viewScorers() {
  crumbs({ label: 'Scorers' });
  const catalog = state.catalog || await api('/api/catalog');
  const scorers = catalog.scorers || catalog.eval_types || [];
  app().innerHTML = `
    <h1>Scorers</h1>
    <p class="lede">How an answer is graded. Pick the one that matches the shape of a correct
    answer, not the one that sounds most sophisticated.</p>
    ${scorers.length ? `
      <div class="grid-scroll"><table class="data">
        <thead><tr><th>eval type</th><th>what it does</th></tr></thead>
        <tbody>${scorers.map((sc) => `
          <tr><td><code>${esc(sc.name || sc)}</code></td>
              <td>${esc(sc.description || sc.what || '')}</td></tr>`).join('')}</tbody>
      </table></div>` : '<p class="hint">No scorer metadata returned.</p>'}`;
}

/* ---------------------------------------------------------------- boot */

window.addEventListener('hashchange', router);

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
  try {
    state.catalog = await api('/api/catalog');
    // The catalog carries no version, but the server stamps one onto the asset
    // URLs — a single source rather than a second thing to keep in sync.
    const stamped = document.querySelector('link[href*="app.css"]')?.getAttribute('href') || '';
    const version = (stamped.match(/[?&]v=([^&]+)/) || [])[1];
    if (version) {
      state.version = version;
      $('#version').textContent = `v${version}`;
    }
  } catch (error) {
    app().innerHTML = `<div class="card"><h2>Cannot reach the server</h2><p>${esc(error.message)}</p></div>`;
    return;
  }
  router();
})();
