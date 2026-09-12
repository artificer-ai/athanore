/**
 * <athanore-cron> — the crontab pane.
 *
 * Five fields, a workflow, a title and a prompt. The prompt is the run's
 * description, so a scheduled run arrives at `prompt` — the haiku seat —
 * looking exactly like one an operator typed.
 */

// The pane's own names for the theme's tokens (D183). The values are
// `tokens.gen.ts`'s — `--color-*` and `--ath-status-*` — read as the
// document resolves them; the fallbacks are Nocturne's, for a document
// that resolves nothing. `--ath-bg` and friends are this file's aliases,
// not names any theme defines.
const TOKENS = {
  '--ath-bg': ['--color-bg', '#161826'],
  '--ath-surface': ['--color-surface', '#232532'],
  '--ath-border': ['--color-divider', 'rgba(233, 233, 237, 0.16)'],
  '--ath-text': ['--color-text', '#e9e9ed'],
  '--ath-muted': ['--color-neutral-500', '#9397ab'],
  '--ath-accent': ['--color-accent', '#9184d9'],
  '--ath-status-ok': ['--ath-status-ok', '#8fbfa4'],
  '--ath-status-bad': ['--ath-status-fail', '#d9868f'],
}

/** `:host` declarations binding every alias above to the live theme. */
function themeVars() {
  const theme = (window.athanore?.theme?.tokens) ?? {}
  return Object.entries(TOKENS)
    .map(([alias, [token, fallback]]) => `${alias}: ${theme[token] || fallback}`)
    .join(';')
}

const PLACEHOLDER = '0 9 * * 1-5'

function when(row) {
  if (!row.enabled) return 'paused'
  if (!row.next) return 'never (nothing in the next 14 days)'
  return `next ${new Date(row.next).toLocaleString()}`
}

class AthanoreCron extends HTMLElement {
  connectedCallback() {
    this.attachShadow({ mode: 'open' })
    const vars = themeVars()
    this.shadowRoot.innerHTML = `
      <style>
        :host { ${vars}; display: block; font: inherit; color: var(--ath-text); }
        form { display: grid; gap: 6px; background: var(--ath-surface);
               border: 1px solid var(--ath-border); border-radius: 8px; padding: 12px; }
        input, select, textarea, button { font: inherit; color: var(--ath-text);
               background: var(--ath-bg); border: 1px solid var(--ath-border);
               border-radius: 5px; padding: 5px 7px; }
        textarea { min-height: 52px; resize: vertical; }
        .cron { font-family: ui-monospace, monospace; }
        .add { color: var(--ath-accent); cursor: pointer; }
        .muted { color: var(--ath-muted); }
        .bad { color: var(--ath-status-bad); }
        .row { display: grid; gap: 2px; padding: 7px 0;
               border-bottom: 1px solid var(--ath-border); }
        .head { display: flex; gap: 9px; align-items: baseline; }
        .head .cron { flex: 1; }
        .head button { background: none; border: none; padding: 0;
                       color: var(--ath-accent); cursor: pointer; }
        ul { list-style: none; margin: 12px 0 0; padding: 0; }
      </style>
      <form>
        <div class="head">
          <select name="workflow"></select>
          <input name="cron" class="cron" placeholder="${PLACEHOLDER}" required>
        </div>
        <input name="title" placeholder="title — becomes the run's" required>
        <textarea name="prompt" placeholder="prompt — becomes the run's description"></textarea>
        <button class="add" type="submit">schedule it</button>
        <span class="muted">minute · hour · day of month · month · day of week
          (0 = Monday). <code>*</code> <code>5</code> <code>1-5</code>
          <code>*/15</code> <code>1,3</code></span>
      </form>
      <p class="bad" hidden></p>
      <ul></ul>`
    this.shadowRoot.querySelector('form')
      .addEventListener('submit', (e) => this.add(e))
    this.load()
  }

  fail(message) {
    const p = this.shadowRoot.querySelector('p')
    p.textContent = message
    p.hidden = !message
  }

  async call(path, init) {
    const r = await window.athanore.fetch(path, init)
    if (!r.ok) {
      // A plugin refusal carries `error` in 08's shape; anything else is
      // a status, and saying which is the difference between "your cron
      // has four fields" and "something went wrong".
      let detail = `${r.status}`
      try { detail = (await r.json()).error ?? detail } catch { /* not JSON */ }
      throw new Error(detail)
    }
    return r.json()
  }

  async load() {
    try {
      const data = await this.call('schedules')
      const select = this.shadowRoot.querySelector('select')
      const chosen = select.value
      select.replaceChildren(...data.workflows.map((name) => {
        const o = document.createElement('option')
        o.value = o.textContent = name
        return o
      }))
      if (chosen) select.value = chosen
      this.draw(data.schedules)
      this.fail('')
    } catch (err) {
      this.fail(String(err.message ?? err))
    }
  }

  async add(event) {
    event.preventDefault()
    const form = event.target
    const body = Object.fromEntries(new FormData(form).entries())
    try {
      await this.call('schedules', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(body),
      })
      form.querySelector('[name=cron]').value = ''
      form.querySelector('[name=title]').value = ''
      form.querySelector('[name=prompt]').value = ''
      await this.load()
    } catch (err) {
      this.fail(String(err.message ?? err))
    }
  }

  async act(id, verb, init) {
    try {
      await this.call(`schedules/${encodeURIComponent(id)}${verb}`, init)
      await this.load()
    } catch (err) {
      this.fail(String(err.message ?? err))
    }
  }

  draw(rows) {
    const list = this.shadowRoot.querySelector('ul')
    list.replaceChildren()
    if (!rows.length) {
      const li = document.createElement('li')
      li.className = 'muted'
      li.textContent = 'nothing scheduled'
      list.append(li)
      return
    }
    for (const row of rows) {
      const li = document.createElement('li')
      li.className = 'row'
      const head = document.createElement('div')
      head.className = 'head'
      const cron = document.createElement('code')
      cron.className = 'cron'
      cron.textContent = row.cron
      head.append(cron)
      for (const [label, verb, init] of [
        ['run now', '/run', { method: 'POST' }],
        [row.enabled ? 'pause' : 'resume', '/toggle', { method: 'POST' }],
        ['delete', '', { method: 'DELETE' }],
      ]) {
        const b = document.createElement('button')
        b.textContent = label
        b.addEventListener('click', () => this.act(row.id, verb, init))
        head.append(b)
      }
      const what = document.createElement('div')
      what.textContent = `${row.workflow} · ${row.title}`
      const meta = document.createElement('div')
      meta.className = row.last_error ? 'bad' : 'muted'
      meta.textContent = row.last_error
        ? `last attempt failed: ${row.last_error}`
        : when(row)
      li.append(head, what, meta)
      list.append(li)
    }
  }
}

customElements.define('athanore-cron', AthanoreCron)
