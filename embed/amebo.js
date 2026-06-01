// amebo embed bundle v0
//
// Registers three web components for use inside other shells (abra view,
// hosted demos, anything that wants amebo intelligence as a widget):
//
//   <amebo-ask>      a question box that posts to /api/qa/ask
//   <amebo-goal>     one goal's state, with dispatch/pause/resume buttons + last 3 events
//   <amebo-goals>    a filtered list of goals (data-status, data-limit) from /api/goals/
//   <amebo-digest>   "what should I look at today?" rendered from /api/digest
//
// Contract with the host shell (per abra view session, 2026-05-31):
//
//   - Shell instantiates the element and sets generic dataset attrs:
//       data-up     — base URL the component fetches from (view-server proxy)
//       data-ref    — full original target URI (e.g. "amebo:goal/42")
//       data-scheme — scheme key from sources.yaml (e.g. "amebo:goal")
//       data-path   — everything after the scheme prefix (e.g. "42")
//   - Component parses data-path itself; shell stays scheme-agnostic.
//   - Org is NOT a component attribute. It is resolved server-side from
//     the authenticated identity (the JWT). Components never carry org.
//   - All HTTP goes to ${data-up}/api/... ; no host or token in this file.
//     The view server holds creds and proxies upstream.
//
// Bundle loading (per Golda, 2026-06-01):
//
//   While amebo and the host (abra view) sit on the same VM behind one
//   nginx, use the same-origin proxy. nginx forwards e.g.
//   /abra-view/up/amebo/* to amebo's backend on 127.0.0.1:8000. The host
//   page loads the bundle from /abra-view/up/amebo/embed/amebo.js and
//   the components call /abra-view/up/amebo/api/... — all same-origin,
//   no CORS, no cross-origin cookie games.
//
//     <script src="/abra-view/up/amebo/embed/amebo.js"></script>
//     <amebo-goal data-up="/abra-view/up/amebo" ...></amebo-goal>
//
//   The bundle also supports cross-origin (data-up="https://amebo.<host>")
//   for the day amebo moves to its own VM — components fetch with
//   credentials: 'include' so cookies ride along either way. Auth is
//   Authorization: Bearer JWT from amebo's Google OAuth; see embed/README.md.
//
// Zero dependencies. Vanilla custom elements, no shadow DOM, host page
// can style via the element tag selectors.

(function () {
  'use strict';
  if (window.__ameboEmbedLoaded) return;
  window.__ameboEmbedLoaded = true;

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function ensureStyles() {
    if (document.getElementById('amebo-embed-styles')) return;
    const s = document.createElement('style');
    s.id = 'amebo-embed-styles';
    s.textContent = `
      amebo-ask, amebo-goal, amebo-digest, amebo-goals, amebo-create-goal {
        display: block;
        font-family: system-ui, -apple-system, sans-serif;
        font-size: 14px;
        color: inherit;
        line-height: 1.4;
      }
      amebo-create-goal .hd { margin-bottom: 8px; }
      amebo-create-goal .hd .why { font-weight: normal; opacity: 0.7; font-size: 12px; }
      amebo-create-goal label { display: block; margin: 8px 0; font-size: 13px; }
      amebo-create-goal label.clawable { display: flex; align-items: center; gap: 6px; }
      amebo-create-goal input[type=text], amebo-create-goal textarea {
        width: 100%; padding: 6px 8px; font: inherit; box-sizing: border-box;
      }
      amebo-create-goal .actions { margin-top: 10px; display: flex; gap: 6px; flex-wrap: wrap; }
      amebo-create-goal button { padding: 6px 12px; cursor: pointer; font: inherit; }
      amebo-create-goal button.commit { font-weight: 600; }
      amebo-create-goal details.feedback { margin: 10px 0; font-size: 12px; opacity: 0.85; }
      amebo-create-goal details.feedback summary { cursor: pointer; }
      amebo-create-goal details.feedback textarea { margin-top: 6px; }
      amebo-create-goal .status { margin-top: 8px; font-size: 12px; }
      amebo-create-goal.saved code, amebo-create-goal .saved code {
        background: rgba(0,0,0,0.06); padding: 1px 4px; border-radius: 3px;
        font-size: 12px;
      }
      amebo-ask form { display: flex; gap: 6px; }
      amebo-ask input[type=text] { flex: 1; padding: 6px 8px; font: inherit; }
      amebo-ask button, amebo-goal button { padding: 6px 10px; cursor: pointer; font: inherit; }
      amebo-ask .answer { margin-top: 8px; white-space: pre-wrap; }
      amebo-ask .sources { margin-top: 6px; font-size: 12px; opacity: 0.7; }
      amebo-goal .status { font-size: 12px; opacity: 0.7; }
      amebo-goal .actions { margin-top: 6px; display: flex; gap: 6px; flex-wrap: wrap; }
      amebo-goal ul.events { list-style: none; padding-left: 0; margin: 8px 0 0; font-size: 12px; }
      amebo-goal ul.events li { padding: 2px 0; border-top: 1px solid rgba(0,0,0,0.06); }
      amebo-goal ul.events .when { opacity: 0.6; margin-right: 6px; }
      amebo-goal ul.events .action { font-family: ui-monospace, monospace; }
      amebo-goal ul.events .summary { opacity: 0.8; }
      amebo-goals ul.goals { list-style: none; padding-left: 0; margin: 0; }
      amebo-goals ul.goals li { display: flex; gap: 8px; align-items: baseline; padding: 4px 0; border-top: 1px solid rgba(0,0,0,0.06); }
      amebo-goals ul.goals .title { flex: 1; }
      amebo-goals ul.goals .status { font-size: 12px; opacity: 0.7; }
      amebo-goals ul.goals .when { font-size: 12px; opacity: 0.5; }
      amebo-goals .empty { font-size: 12px; opacity: 0.6; }
      amebo-digest ul { padding-left: 1.2em; margin: 4px 0; }
      .amebo-error { color: #b00; font-size: 12px; }
      .amebo-loading { opacity: 0.6; font-size: 12px; }
    `;
    document.head.appendChild(s);
  }

  function upBase(el) {
    const u = el.dataset.up;
    return (u && u.replace(/\/+$/, '')) || null;
  }

  // Render an error in-place. Accepts an Error (HttpError preferred) or a
  // plain string. The console always gets the full picture (method, url,
  // status, parsed body) so devs can diagnose without screen-scraping the
  // UI.
  function showError(el, errOrMsg) {
    if (errOrMsg instanceof HttpError) {
      const tip = `${errOrMsg.method} ${errOrMsg.url} → ${errOrMsg.status}`;
      el.innerHTML = `<div class="amebo-error" title="${esc(tip)}">amebo: ${esc(errOrMsg.message)}</div>`;
      return;
    }
    const msg = errOrMsg && errOrMsg.message ? errOrMsg.message : String(errOrMsg);
    el.innerHTML = `<div class="amebo-error">amebo: ${esc(msg)}</div>`;
  }

  // Best-effort body parser: try JSON, fall back to text.
  async function readBody(r) {
    let raw = '';
    try { raw = await r.text(); } catch (_) { return null; }
    if (!raw) return null;
    try { return JSON.parse(raw); } catch (_) { return raw; }
  }

  // Pick the most useful human-readable message from amebo's error shapes:
  //   { detail: [{msg, loc, ...}, ...] }    Pydantic validation (422)
  //   { detail: "..." }                      FastAPI HTTPException
  //   { error, message }                     amebo's global exception handler
  //   "...text..."                           anything else
  function bestMessage(body, status) {
    if (body == null) return `http ${status}`;
    if (typeof body === 'string') return body.slice(0, 240) || `http ${status}`;
    if (Array.isArray(body.detail) && body.detail.length) {
      return body.detail.map(d => {
        const loc = Array.isArray(d.loc) ? d.loc.join('.') : '';
        return (loc ? loc + ': ' : '') + (d.msg || JSON.stringify(d));
      }).join('; ');
    }
    if (typeof body.detail === 'string') return body.detail;
    if (body.message) return String(body.message);
    if (body.error) return String(body.error);
    return `http ${status}`;
  }

  class HttpError extends Error {
    constructor(method, url, status, body) {
      super(bestMessage(body, status));
      this.name = 'HttpError';
      this.method = method;
      this.url = url;
      this.status = status;
      this.body = body;
    }
  }

  function relTime(iso) {
    if (!iso) return '';
    const t = Date.parse(iso);
    if (isNaN(t)) return '';
    const s = Math.max(0, Math.round((Date.now() - t) / 1000));
    if (s < 60) return s + 's ago';
    if (s < 3600) return Math.round(s / 60) + 'm ago';
    if (s < 86400) return Math.round(s / 3600) + 'h ago';
    return Math.round(s / 86400) + 'd ago';
  }

  function trunc(s, n) {
    s = String(s == null ? '' : s);
    return s.length > n ? s.slice(0, n - 1) + '…' : s;
  }

  async function jget(url) {
    let r;
    try {
      r = await fetch(url, { credentials: 'include' });
    } catch (e) {
      console.error('[amebo] network error', { method: 'GET', url, error: e });
      throw new Error('network error: ' + (e && e.message || e));
    }
    if (!r.ok) {
      const body = await readBody(r);
      console.error('[amebo] http error', { method: 'GET', url, status: r.status, body });
      throw new HttpError('GET', url, r.status, body);
    }
    return r.json();
  }

  async function jpost(url, payload) {
    let r;
    try {
      r = await fetch(url, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload || {}),
      });
    } catch (e) {
      console.error('[amebo] network error', { method: 'POST', url, error: e, payload });
      throw new Error('network error: ' + (e && e.message || e));
    }
    if (!r.ok) {
      const body = await readBody(r);
      console.error('[amebo] http error', { method: 'POST', url, status: r.status, body, payload });
      throw new HttpError('POST', url, r.status, body);
    }
    return r.json();
  }

  // ---- <amebo-ask> --------------------------------------------------------

  class AmeboAsk extends HTMLElement {
    connectedCallback() {
      ensureStyles();
      const base = upBase(this);
      if (!base) return showError(this, 'missing data-up');
      this.innerHTML = `
        <form>
          <input type="text" name="q" placeholder="Ask amebo…" autocomplete="off">
          <button type="submit">Ask</button>
        </form>
        <div class="answer"></div>
        <div class="sources"></div>
      `;
      const form = this.querySelector('form');
      const answer = this.querySelector('.answer');
      const sources = this.querySelector('.sources');
      form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const q = form.q.value.trim();
        if (!q) return;
        answer.innerHTML = '<span class="amebo-loading">thinking…</span>';
        sources.textContent = '';
        try {
          const data = await jpost(`${base}/api/qa/ask`, { question: q });
          answer.textContent = data.answer || '(no answer)';
          if (Array.isArray(data.sources) && data.sources.length) {
            sources.textContent = `sources: ${data.sources.length}`;
          }
        } catch (err) {
          showError(answer, err);
        }
      });
    }
  }

  // ---- <amebo-goal> -------------------------------------------------------

  class AmeboGoal extends HTMLElement {
    async connectedCallback() {
      ensureStyles();
      const base = upBase(this);
      const id = this.dataset.path || this.getAttribute('goal-id');
      if (!base) return showError(this, 'missing data-up');
      if (!id) return showError(this, 'missing data-path');
      this.innerHTML = '<div class="amebo-loading">loading goal…</div>';
      this._base = base;
      this._goalId = id;
      await this._refresh();
    }

    async _refresh() {
      try {
        const [g, events] = await Promise.all([
          jget(`${this._base}/api/goals/${encodeURIComponent(this._goalId)}`),
          jget(`${this._base}/api/goals/${encodeURIComponent(this._goalId)}/events`)
            .catch(() => []),
        ]);
        this._render(g, events);
      } catch (err) {
        showError(this, err);
      }
    }

    _render(g, events) {
      const goalId = g.goal_id || g.id || this._goalId;
      const recent = (Array.isArray(events) ? events : []).slice(0, 3);
      const eventsHtml = recent.length
        ? `<ul class="events">${recent.map((e) => `
            <li>
              <span class="when">${esc(relTime(e.created_at))}</span>
              <span class="action">${esc(e.action || '')}</span>${
                e.result_summary
                  ? `<span class="summary"> — ${esc(trunc(e.result_summary, 80))}</span>`
                  : ''
              }
            </li>
          `).join('')}</ul>`
        : '';
      this.innerHTML = `
        <div><strong>${esc(g.title)}</strong></div>
        <div class="status">status: ${esc(g.status || 'unknown')} · id: ${esc(goalId)}</div>
        <div class="actions">
          <button data-action="dispatch-now">Dispatch now</button>
          <button data-action="pause">Pause</button>
          <button data-action="resume">Resume</button>
        </div>
        ${eventsHtml}
      `;
      this.querySelectorAll('button[data-action]').forEach((b) => {
        b.addEventListener('click', async () => {
          const path = b.dataset.action;
          try {
            await jpost(`${this._base}/api/goals/${encodeURIComponent(goalId)}/${path}`, {});
            await this._refresh();
          } catch (err) {
            showError(this, err);
          }
        });
      });
    }
  }

  // ---- <amebo-digest> -----------------------------------------------------

  class AmeboDigest extends HTMLElement {
    async connectedCallback() {
      ensureStyles();
      const base = upBase(this);
      if (!base) return showError(this, 'missing data-up');
      this.innerHTML = '<div class="amebo-loading">loading digest…</div>';
      try {
        const d = await jget(`${base}/api/digest`);
        const items = (d.items || [])
          .map((i) => `<li>${esc(i.text || i.title || '')}</li>`)
          .join('');
        this.innerHTML = `
          <div><strong>${esc(d.heading || 'Today')}</strong></div>
          <ul>${items}</ul>
        `;
      } catch (err) {
        showError(this, err);
      }
    }
  }

  // ---- <amebo-goals> ------------------------------------------------------

  class AmeboGoals extends HTMLElement {
    async connectedCallback() {
      ensureStyles();
      const base = upBase(this);
      if (!base) return showError(this, 'missing data-up');
      const status = this.dataset.status || '';
      const limit = parseInt(this.dataset.limit || '20', 10);
      const params = new URLSearchParams();
      if (status) params.set('status', status);
      if (limit) params.set('limit', String(limit));
      const qs = params.toString();
      const url = `${base}/api/goals/${qs ? '?' + qs : ''}`;
      this.innerHTML = '<div class="amebo-loading">loading goals…</div>';
      try {
        const goals = await jget(url);
        this._render(Array.isArray(goals) ? goals : []);
      } catch (err) {
        showError(this, err);
      }
    }

    _render(goals) {
      if (goals.length === 0) {
        this.innerHTML = '<div class="empty">No goals.</div>';
        return;
      }
      const items = goals.map((g) => `
        <li>
          <span class="title"><strong>${esc(g.title || '')}</strong></span>
          <span class="status">${esc(g.status || '')}</span>
          <span class="when">${esc(relTime(g.updated_at || g.created_at))}</span>
        </li>
      `).join('');
      this.innerHTML = `<ul class="goals">${items}</ul>`;
    }
  }

  // ---- <amebo-create-goal> ------------------------------------------------
  // A clarifying / placement component.
  //
  // Takes free text from the user. Calls /api/intentions/place which uses
  // amebo's AI to propose where the thought belongs in the user's abra map
  // (name, content summary, labels, optional cron if amebo should actively
  // work on it). User edits any field, can re-propose with free-text
  // feedback ("no, this is a principle not a goal"), and confirms — at
  // which point /api/intentions/commit writes to abra and (if clawable)
  // creates an amebo goal stamped with a RUN_BY binding pointing at it.
  //
  // Attributes:
  //   data-up      base URL of the amebo proxy mount (required)
  //   data-scope   defaults to "golda"
  //   data-name    optional — if set, the component is in extend mode
  //                and assumes that name; the user is adding to it.

  class AmeboCreateGoal extends HTMLElement {
    connectedCallback() {
      ensureStyles();
      this._base = upBase(this);
      if (!this._base) return showError(this, 'missing data-up');
      this._scope = this.dataset.scope || 'golda';
      this._nameHint = this.dataset.name || null;
      this._proposal = null;
      this._renderInput();
    }

    _renderInput(prev) {
      const title = this._nameHint
        ? `Add to <em>${esc(this._nameHint)}</em>`
        : 'Place a new thought';
      this.innerHTML = `
        <div class="amebo-create-goal">
          <div class="hd"><strong>${title}</strong></div>
          <textarea class="input" rows="4"
            placeholder="What's on your mind? Amebo will figure out where it goes."
            >${esc(prev || '')}</textarea>
          <div class="actions">
            <button class="propose" type="button">Propose placement</button>
          </div>
          <div class="status"></div>
        </div>
      `;
      this.querySelector('button.propose').addEventListener('click', () => this._propose());
    }

    async _propose(feedback) {
      const text = (this.querySelector('textarea.input') || {}).value || '';
      if (!text.trim()) {
        this._setStatus('type something first.');
        return;
      }
      this._setStatus('thinking…', true);
      try {
        const body = { text, scope: this._scope };
        if (this._nameHint) body.name = this._nameHint;
        if (feedback) body.feedback = feedback;
        const p = await jpost(`${this._base}/api/intentions/place`, body);
        this._proposal = p;
        this._renderProposal(text, p);
      } catch (err) {
        showError(this, err);
      }
    }

    _renderProposal(originalText, p) {
      const cronVal = p.cron || '';
      const labelsStr = (p.labels || []).join(', ');
      this.innerHTML = `
        <div class="amebo-create-goal proposal">
          <div class="hd"><strong>Proposed placement</strong>${
            p.reasoning ? `<span class="why"> — ${esc(p.reasoning)}</span>` : ''
          }</div>

          <label>Name<br><input class="f-name" type="text" value="${esc(p.name)}"></label>
          <label>Scope<br><input class="f-scope" type="text" value="${esc(p.scope)}"></label>
          <label>Content (what gets stored)<br><textarea class="f-content" rows="5">${esc(p.content_summary)}</textarea></label>
          <label>Labels (comma-separated)<br><input class="f-labels" type="text" value="${esc(labelsStr)}"></label>

          <label class="clawable">
            <input type="checkbox" class="f-clawable" ${p.make_clawable ? 'checked' : ''}>
            Make this a clawable goal (amebo will actively work on it)
          </label>
          <div class="claw-fields" ${p.make_clawable ? '' : 'hidden'}>
            <label>Title<br><input class="f-title" type="text" value="${esc(p.title)}"></label>
            <label>Description<br><textarea class="f-desc" rows="2">${esc(p.description)}</textarea></label>
            <label>Cron (blank = manual)<br><input class="f-cron" type="text" value="${esc(cronVal)}" placeholder="0 9 * * 1"></label>
          </div>

          <details class="feedback">
            <summary>Not quite right? Tell amebo what to fix</summary>
            <textarea class="f-feedback" rows="2" placeholder="e.g. 'this is a principle not a goal' or 'watch weekly not daily'"></textarea>
            <button class="re-propose" type="button">Re-propose</button>
          </details>

          <div class="actions">
            <button class="commit" type="button">Save to abra</button>
            <button class="cancel" type="button">Start over</button>
          </div>
          <div class="status"></div>
        </div>
      `;

      this.querySelector('.f-clawable').addEventListener('change', (e) => {
        const fields = this.querySelector('.claw-fields');
        if (e.target.checked) fields.removeAttribute('hidden');
        else fields.setAttribute('hidden', '');
      });
      this.querySelector('button.commit').addEventListener('click', () => this._commit());
      this.querySelector('button.cancel').addEventListener('click', () => this._renderInput(originalText));
      this.querySelector('button.re-propose').addEventListener('click', () => {
        const fb = (this.querySelector('.f-feedback') || {}).value || '';
        // re-render the input so we can re-call propose with the original text + feedback
        const text = originalText;
        this._renderInput(text);
        // populate then propose
        const ta = this.querySelector('textarea.input');
        if (ta) ta.value = text;
        this._propose(fb);
      });
    }

    _collectProposal() {
      const labels = (this.querySelector('.f-labels').value || '')
        .split(',').map(s => s.trim()).filter(Boolean);
      const clawable = this.querySelector('.f-clawable').checked;
      return {
        scope: this.querySelector('.f-scope').value.trim() || this._scope,
        name: this.querySelector('.f-name').value.trim(),
        name_is_new: !!this._proposal && this._proposal.name_is_new,
        content_summary: this.querySelector('.f-content').value,
        labels,
        make_clawable: clawable,
        cron: clawable ? (this.querySelector('.f-cron').value.trim() || null) : null,
        title: clawable ? (this.querySelector('.f-title').value.trim() || '') : '',
        description: clawable ? (this.querySelector('.f-desc').value || '') : '',
        reasoning: this._proposal ? this._proposal.reasoning : '',
      };
    }

    async _commit() {
      const proposal = this._collectProposal();
      if (!proposal.name) {
        this._setStatus('name is required.');
        return;
      }
      if (!proposal.content_summary.trim()) {
        this._setStatus('content is empty.');
        return;
      }
      this._setStatus('saving…', true);
      try {
        const r = await jpost(`${this._base}/api/intentions/commit`, proposal);
        this._renderSaved(r);
      } catch (err) {
        showError(this, err);
      }
    }

    _renderSaved(r) {
      const goalLine = r.goal_id
        ? `<div>Created amebo goal <code>${esc(r.goal_id)}</code> — claw will pick it up on its next tick.</div>`
        : '';
      this.innerHTML = `
        <div class="amebo-create-goal saved">
          <div class="hd"><strong>Saved.</strong></div>
          <div>Name: <code>${esc(r.scope)}/${esc(r.name)}</code></div>
          <div>Content blob id: <code>${esc(r.content_id)}</code></div>
          <div>${esc(r.bindings_written)} binding${r.bindings_written === 1 ? '' : 's'} written. Labels: ${esc((r.labels_set || []).join(', ') || '(none)')}.</div>
          ${goalLine}
          <div class="actions">
            <button class="again" type="button">Place another</button>
          </div>
        </div>
      `;
      this.querySelector('button.again').addEventListener('click', () => this._renderInput(''));
    }

    _setStatus(msg, loading) {
      const el = this.querySelector('.status');
      if (!el) return;
      el.className = 'status' + (loading ? ' amebo-loading' : '');
      el.textContent = msg || '';
    }
  }

  if (!customElements.get('amebo-ask')) customElements.define('amebo-ask', AmeboAsk);
  if (!customElements.get('amebo-goal')) customElements.define('amebo-goal', AmeboGoal);
  if (!customElements.get('amebo-goals')) customElements.define('amebo-goals', AmeboGoals);
  if (!customElements.get('amebo-digest')) customElements.define('amebo-digest', AmeboDigest);
  if (!customElements.get('amebo-create-goal')) customElements.define('amebo-create-goal', AmeboCreateGoal);
})();
