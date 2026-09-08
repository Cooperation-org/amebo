/* Echo — one person's lines on a timeline.
   Data: /api/echo/ (routes/echo.py). Auth: the amebo session cookie.
   Everything on screen can be pressed, edited, or moved (UX_PRINCIPLES §2, §4, §5).
   Dragging always has a button alternative (WCAG 2.5.7). */
(() => {
  const API = '/api/echo/';
  const $ = (id) => document.getElementById(id);
  const PALETTE = 10;

  let lines = [];            // every line this person has
  let parentId = null;       // drill-down: which line we are inside (null = top)
  let filterCat = null;      // header chip filter
  let openId = null;         // line whose action bar is open
  let editingId = null;

  // ---------- dates ----------
  const pad = (n) => String(n).padStart(2, '0');
  const iso = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  const today = () => iso(new Date());
  const shift = (isoDate, days) => { const d = new Date(isoDate + 'T00:00'); d.setDate(d.getDate() + days); return iso(d); };
  const dayLabel = (isoDate) => {
    const t = today();
    const d = new Date(isoDate + 'T00:00');
    const name = d.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' });
    if (isoDate === t) return `Today · ${name}`;
    if (isoDate === shift(t, 1)) return `Tomorrow · ${name}`;
    if (isoDate === shift(t, -1)) return `Yesterday · ${name}`;
    const sameYear = d.getFullYear() === new Date().getFullYear();
    return sameYear ? name : d.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' });
  };

  // ---------- api ----------
  async function call(method, path, body) {
    const r = await fetch(API + path, {
      method, credentials: 'include',
      headers: body ? { 'Content-Type': 'application/json' } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
    if (r.status === 401) { showSignin(); throw new Error('signed out'); }
    if (!r.ok) { toast('Not saved'); throw new Error(`${method} ${path} ${r.status}`); }
    return r.status === 204 ? null : r.json();
  }
  const load = async () => { lines = await call('GET', ''); };
  async function add(text) {
    const line = await call('POST', '', { text, on_date: today(), category: filterCat, parent_id: parentId });
    lines.push(line); render();
  }
  async function patch(id, changes) {
    const line = await call('PATCH', String(id), changes);
    lines = lines.map((l) => (l.id === id ? line : l)); render();
  }
  async function remove(id) {
    await call('DELETE', String(id));
    const gone = new Set([id]);
    let grew = true;
    while (grew) { grew = false; for (const l of lines) if (l.parent_id && gone.has(l.parent_id) && !gone.has(l.id)) { gone.add(l.id); grew = true; } }
    lines = lines.filter((l) => !gone.has(l.id)); openId = null; render();
  }

  // ---------- categories ----------
  const categories = () => [...new Set(lines.map((l) => l.category).filter(Boolean))].sort();
  const colorOf = (cat) => { let h = 0; for (const ch of cat) h = (h * 31 + ch.charCodeAt(0)) >>> 0; return `var(--c${h % PALETTE})`; };
  const byId = (id) => lines.find((l) => l.id === id);
  const childCount = (id) => lines.filter((l) => l.parent_id === id).length;

  // ---------- render ----------
  function render() {
    renderChips();
    renderCrumb();
    renderLine();
  }

  function chip(label, { pressed = false, swatch = null, onPress, drop = null } = {}) {
    const b = document.createElement('button');
    b.type = 'button'; b.className = 'chip'; b.setAttribute('aria-pressed', String(pressed));
    if (swatch) { const s = document.createElement('span'); s.className = 'swatch'; s.style.setProperty('--swatch', swatch); b.append(s); }
    b.append(label);
    b.addEventListener('click', onPress);
    if (drop) { b.dataset.drop = drop.kind; b.dataset.dropValue = drop.value; }
    return b;
  }

  function renderChips() {
    const box = $('chips'); box.textContent = '';
    box.append(chip('All', { pressed: filterCat === null, onPress: () => { filterCat = null; render(); } }));
    for (const c of categories()) {
      box.append(chip(c, { pressed: filterCat === c, swatch: colorOf(c), drop: { kind: 'category', value: c },
        onPress: () => { filterCat = filterCat === c ? null : c; render(); } }));
    }
    box.append(chip('+', { onPress: (e) => newCategoryChip(e.currentTarget) }));
  }

  function newCategoryChip(plus) {
    const b = document.createElement('span'); b.className = 'chip';
    const input = document.createElement('input'); input.type = 'text'; input.setAttribute('aria-label', 'New category');
    b.append(input); plus.replaceWith(b); input.focus();
    const done = () => { const v = input.value.trim(); if (v) { filterCat = v; } render(); };
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); done(); } if (e.key === 'Escape') render(); });
    input.addEventListener('blur', done);
  }

  function renderCrumb() {
    const nav = $('crumb');
    const parent = parentId && byId(parentId);
    nav.hidden = !parent;
    if (parent) $('crumb-text').textContent = parent.text;
  }

  function renderLine() {
    const main = $('line'); main.textContent = '';
    const visible = lines.filter((l) => l.parent_id === parentId && (filterCat === null || l.category === filterCat));
    const days = new Set(visible.map((l) => l.on_date));
    days.add(today()); days.add(shift(today(), 1));
    const ordered = [...days].sort();
    for (const d of ordered) {
      const sec = document.createElement('section');
      sec.className = 'day' + (d === today() ? ' today' : ''); sec.dataset.drop = 'date'; sec.dataset.dropValue = d;
      const h = document.createElement('h2'); h.textContent = dayLabel(d); sec.append(h);
      const ul = document.createElement('ul');
      for (const l of visible.filter((x) => x.on_date === d)) ul.append(renderEntry(l));
      sec.append(ul); main.append(sec);
    }
    const todaySec = main.querySelector('.day.today');
    if (todaySec && !render.scrolledOnce) { render.scrolledOnce = true; todaySec.scrollIntoView({ block: 'start' }); window.scrollBy(0, -120); }
  }

  function renderEntry(l) {
    const li = document.createElement('li');
    li.className = 'entry' + (l.done_at ? ' done' : ''); li.dataset.id = l.id; li.dataset.drop = 'parent'; li.dataset.dropValue = l.id;

    const check = document.createElement('button'); check.type = 'button'; check.className = 'check';
    check.setAttribute('aria-label', l.done_at ? 'Done' : 'Not done'); check.setAttribute('aria-pressed', String(!!l.done_at));
    check.append(document.createElement('span'));
    check.addEventListener('click', () => patch(l.id, { done: !l.done_at }));

    const text = document.createElement('div'); text.className = 'text'; text.textContent = l.text; text.tabIndex = 0; text.setAttribute('role', 'button');
    text.addEventListener('click', () => editText(l, text));
    text.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); editText(l, text); } });

    const tags = document.createElement('div'); tags.className = 'tags';
    if (l.category) { const c = document.createElement('span'); c.className = 'cat'; c.textContent = l.category; c.style.setProperty('--swatch', colorOf(l.category)); tags.append(c); }
    const n = childCount(l.id);
    if (n) { const o = document.createElement('button'); o.type = 'button'; o.className = 'open'; o.textContent = `${n} ›`; o.setAttribute('aria-label', `Open, ${n} inside`); o.addEventListener('click', () => { parentId = l.id; openId = null; render(); }); tags.append(o); }
    const more = document.createElement('button'); more.type = 'button'; more.className = 'more'; more.textContent = '⋯'; more.setAttribute('aria-label', 'Move, categorize, or remove'); more.setAttribute('aria-expanded', String(openId === l.id));
    more.addEventListener('click', () => { openId = openId === l.id ? null : l.id; render(); });
    tags.append(more);

    li.append(check, text, tags);
    if (openId === l.id) li.append(renderActions(l));
    enableDrag(li, l);
    return li;
  }

  function renderActions(l) {
    const box = document.createElement('div'); box.className = 'actions';
    const t = today();
    const when = document.createElement('div'); when.className = 'row';
    const dayBtn = (label, d) => { const b = document.createElement('button'); b.type = 'button'; b.className = 'btn'; b.textContent = label; b.setAttribute('aria-pressed', String(l.on_date === d)); b.addEventListener('click', () => patch(l.id, { on_date: d })); return b; };
    when.append(dayBtn('Today', t), dayBtn('Tomorrow', shift(t, 1)), dayBtn('Next week', shift(t, 7)));
    const date = document.createElement('input'); date.type = 'date'; date.value = l.on_date; date.setAttribute('aria-label', 'Day');
    date.addEventListener('change', () => { if (date.value) patch(l.id, { on_date: date.value }); });
    when.append(date);

    const cats = document.createElement('div'); cats.className = 'row';
    for (const c of categories()) cats.append(chip(c, { pressed: l.category === c, swatch: colorOf(c), onPress: () => patch(l.id, { category: l.category === c ? null : c }) }));
    cats.append(chip('+', { onPress: (e) => {
      const b = document.createElement('span'); b.className = 'chip';
      const input = document.createElement('input'); input.type = 'text'; input.setAttribute('aria-label', 'New category');
      b.append(input); e.currentTarget.replaceWith(b); input.focus();
      const done = () => { const v = input.value.trim(); if (v) patch(l.id, { category: v }); else render(); };
      input.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') { ev.preventDefault(); done(); } if (ev.key === 'Escape') render(); });
      input.addEventListener('blur', done);
    } }));

    const more = document.createElement('div'); more.className = 'row';
    const open = document.createElement('button'); open.type = 'button'; open.className = 'btn'; open.textContent = 'Open ›';
    open.addEventListener('click', () => { parentId = l.id; openId = null; render(); });
    more.append(open);
    if (parentId !== null) {
      const parent = byId(parentId);
      const out = document.createElement('button'); out.type = 'button'; out.className = 'btn'; out.textContent = '‹ Move out';
      out.addEventListener('click', () => patch(l.id, { parent_id: parent ? parent.parent_id : null }));
      more.append(out);
    }
    const del = document.createElement('button'); del.type = 'button'; del.className = 'btn danger'; del.textContent = 'Remove';
    del.addEventListener('click', () => { if (del.dataset.armed) remove(l.id); else { del.dataset.armed = '1'; del.textContent = childCount(l.id) ? `Remove it and the ${childCount(l.id)} inside?` : 'Remove?'; } });
    more.append(del);

    box.append(when, cats, more);
    return box;
  }

  function editText(l, node) {
    if (editingId === l.id) return;
    editingId = l.id;
    const input = document.createElement('input'); input.type = 'text'; input.value = l.text; input.setAttribute('aria-label', 'Edit');
    node.textContent = ''; node.append(input); input.focus(); input.setSelectionRange(input.value.length, input.value.length);
    let finished = false;
    const finish = async (save) => {
      if (finished) return; finished = true; editingId = null;
      const v = input.value.trim();
      if (save && v && v !== l.text) await patch(l.id, { text: v }); else render();
    };
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); finish(true); } if (e.key === 'Escape') finish(false); });
    input.addEventListener('blur', () => finish(true));
  }

  // ---------- drag (pointer events; long-press on touch so scrolling still works) ----------
  function enableDrag(li, l) {
    let timer = null, dragging = false, startX = 0, startY = 0, target = null;
    const clearDrop = () => document.querySelectorAll('.drop').forEach((n) => n.classList.remove('drop'));
    const findTarget = (x, y) => {
      const el = document.elementFromPoint(x, y);
      const t = el && el.closest('[data-drop]');
      if (!t || t === li || (t.dataset.drop === 'parent' && Number(t.dataset.dropValue) === l.id)) return null;
      return t;
    };
    li.addEventListener('pointerdown', (e) => {
      if (e.target.closest('button, input, .text')) return;
      startX = e.clientX; startY = e.clientY;
      const begin = () => { dragging = true; li.classList.add('dragging'); li.setPointerCapture(e.pointerId); };
      if (e.pointerType === 'touch') timer = setTimeout(begin, 350); else begin();
    });
    li.addEventListener('pointermove', (e) => {
      if (!dragging) { if (timer && Math.hypot(e.clientX - startX, e.clientY - startY) > 8) { clearTimeout(timer); timer = null; } return; }
      e.preventDefault();
      const t = findTarget(e.clientX, e.clientY);
      if (t !== target) { clearDrop(); target = t; if (t) t.classList.add('drop'); }
    });
    const end = (e) => {
      if (timer) { clearTimeout(timer); timer = null; }
      if (!dragging) return;
      dragging = false; li.classList.remove('dragging'); clearDrop();
      const t = target; target = null;
      if (!t) return;
      const v = t.dataset.dropValue;
      if (t.dataset.drop === 'date') patch(l.id, { on_date: v });
      else if (t.dataset.drop === 'category') patch(l.id, { category: v });
      else if (t.dataset.drop === 'parent') patch(l.id, { parent_id: Number(v) });
    };
    li.addEventListener('pointerup', end);
    li.addEventListener('pointercancel', end);
    li.style.touchAction = 'pan-y';
  }

  // ---------- toast / signin ----------
  let toastTimer = null;
  function toast(msg) { const t = $('toast'); t.textContent = msg; t.hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => { t.hidden = true; }, 2500); }
  function showSignin() {
    $('app').hidden = true; $('signin').hidden = false;
    $('signin-link').href = '/api/auth/oidc/login?next=' + encodeURIComponent(location.origin + location.pathname);
  }

  // ---------- boot ----------
  $('add').addEventListener('submit', async (e) => {
    e.preventDefault();
    const input = $('add-text'); const v = input.value.trim();
    if (!v) return; input.value = ''; await add(v); input.focus();
  });
  $('up').addEventListener('click', () => { const p = byId(parentId); parentId = p ? p.parent_id : null; openId = null; render(); });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && openId !== null) { openId = null; render(); } });

  (async () => {
    try { await load(); } catch { return; }
    $('signin').hidden = true; $('app').hidden = false; render(); $('add-text').focus();
  })();
})();
