/**
 * <athanore-chat> — the conversation, and a box to add to it.
 *
 * One route for the state (`turns`), one for the send (`say`), and the
 * tab's event feed to know when either changed. The element never
 * decides anything: whether it is your turn is `pending` from the
 * server, and a send is an answer to that request — the same answer the
 * request pane or `athanore` on the command line would give.
 */

const REFRESH_ON = [
  'log.appended',
  'request.opened',
  'request.answered',
  'run.completed',
  'run.failed',
  'run.cancelled',
  'task.started',
]

class AthanoreChat extends HTMLElement {
  connectedCallback() {
    this.runId = this.getAttribute('run-id')
    this.attachShadow({ mode: 'open' })
    // The theme's tokens, as the document resolves them (D183). These
    // are `tokens.gen.ts`'s names — `--color-*` and `--ath-*` — not the
    // `--ath-bg`/`--ath-surface` family, which no theme defines.
    const t = window.athanore?.theme?.tokens ?? {}
    const tok = (name, fallback) => t[name] || fallback
    const vars = [
      `--bg: ${tok('--color-bg', '#161826')}`,
      `--surface: ${tok('--color-surface', '#232532')}`,
      `--text: ${tok('--color-text', '#e9e9ed')}`,
      `--accent: ${tok('--color-accent', '#9184d9')}`,
      `--accent-deep: ${tok('--color-accent-800', '#423a6a')}`,
      `--muted: ${tok('--color-neutral-500', '#9397ab')}`,
      `--divider: ${tok('--color-divider', 'rgba(233,233,237,0.16)')}`,
      `--bad: ${tok('--ath-status-fail', '#d9868f')}`,
      `--radius: ${tok('--ath-radius', '6px')}`,
    ].join(';')
    this.shadowRoot.innerHTML = `
      <style>
        :host { ${vars}; display: flex; flex-direction: column; height: 100%;
                min-height: 320px; font: inherit; color: var(--text); }
        .log { flex: 1; overflow-y: auto; display: flex; flex-direction: column;
               gap: 8px; padding: 14px 12px; }
        .msg { max-width: 78%; padding: 8px 12px; border-radius: 16px;
               white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.45;
               font-size: 0.95em; }
        .msg.you { align-self: flex-end; background: var(--accent-deep);
                   border-bottom-right-radius: 4px; }
        .msg.them { align-self: flex-start; background: var(--surface);
                    border-bottom-left-radius: 4px; }
        .who { display: block; font-size: 0.75em; letter-spacing: 0.02em;
               color: var(--muted); margin-bottom: 2px; }
        .msg.you .who { text-align: right; }
        .state { margin: 0; padding: 0 12px 6px; font-size: 0.85em; color: var(--muted); }
        .state.bad { color: var(--bad); }
        form { display: flex; gap: 6px; padding: 10px 12px;
               border-top: 1px solid var(--divider); background: var(--surface); }
        textarea { flex: 1; min-height: 40px; max-height: 160px; resize: vertical;
                   font: inherit; color: var(--text); background: var(--bg);
                   border: 1px solid var(--divider); border-radius: var(--radius); padding: 6px 8px; }
        textarea:focus { outline: 1px solid var(--accent); }
        button { font: inherit; padding: 6px 14px; border-radius: var(--radius); cursor: pointer;
                 color: var(--bg); background: var(--accent); border: none; }
        button:disabled, textarea:disabled { opacity: 0.5; cursor: default; }
      </style>
      <div class="log"></div>
      <p class="state"></p>
      <form>
        <textarea name="text" rows="1" placeholder="say something — /quit ends it"></textarea>
        <button type="submit">send</button>
      </form>`
    this.log = this.shadowRoot.querySelector('.log')
    this.state = this.shadowRoot.querySelector('.state')
    this.form = this.shadowRoot.querySelector('form')
    this.box = this.shadowRoot.querySelector('textarea')
    this.button = this.shadowRoot.querySelector('button')
    this.form.addEventListener('submit', (e) => this.send(e))
    // Enter sends, shift+enter is a newline — the chat convention, and
    // the one thing a plain <textarea> in a form does not do.
    this.box.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        this.form.requestSubmit()
      }
    })
    try {
      this.unsubscribe = window.athanore.subscribe(REFRESH_ON, (event) => {
        if (!event.run_id || event.run_id === this.runId) this.load()
      })
    } catch (err) {
      this.fail(`live updates off: ${err.message}`)
    }
    this.load()
  }

  disconnectedCallback() {
    this.unsubscribe?.()
  }

  fail(message) {
    this.state.textContent = message
    this.state.classList.toggle('bad', Boolean(message))
  }

  async call(path, init) {
    const r = await window.athanore.fetch(`${path}?run_id=${encodeURIComponent(this.runId)}`, init)
    if (!r.ok) {
      let detail = `${r.status}`
      try { detail = (await r.json()).error ?? detail } catch { /* not JSON */ }
      throw new Error(detail)
    }
    return r.json()
  }

  async load() {
    try {
      this.render(await this.call('turns'))
    } catch (err) {
      this.fail(err.message)
    }
  }

  render(view) {
    const stuck = this.log.scrollTop + this.log.clientHeight >= this.log.scrollHeight - 8
    this.log.replaceChildren(
      ...view.turns.map((turn) => {
        const div = document.createElement('div')
        div.className = `msg ${turn.who === 'you' ? 'you' : 'them'}`
        const who = document.createElement('span')
        who.className = 'who'
        who.textContent = turn.who
        div.append(who, turn.text)
        return div
      }),
    )
    if (stuck) this.log.scrollTop = this.log.scrollHeight

    const over = view.run.status !== 'running' && view.run.status !== 'queued'
    const yours = view.pending !== null
    this.box.disabled = over || !yours
    this.button.disabled = over || !yours
    this.state.classList.remove('bad')
    if (over) this.state.textContent = `run ${view.run.status}`
    else if (yours) this.state.textContent = ''
    else this.state.textContent = `${view.agent} is answering…`
    if (yours && !over) this.box.focus()
  }

  async send(e) {
    e.preventDefault()
    const text = this.box.value.trim()
    if (!text) return
    this.button.disabled = true
    try {
      this.render(await this.call('say', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ text }),
      }))
      this.box.value = ''
    } catch (err) {
      this.fail(err.message)
      this.button.disabled = false
    }
  }
}

customElements.define('athanore-chat', AthanoreChat)
