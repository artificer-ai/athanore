/**
 * <athanore-chat> — the conversation, and a box to add to it.
 *
 * One route for the state (`turns`), one for the send (`say`), one for
 * the reply as it is typed (`draft`), and the tab's event feed to know
 * when any of them changed. The element never decides anything: whether
 * it is your turn is `pending` from the server, and a send is an answer
 * to that request — the same answer the request pane or `athanore` on
 * the command line would give.
 *
 * The draft follows `task.stream`, the ephemeral event the transcript
 * writer publishes per flushed batch (08 §Tasks). Each one is a pull of
 * `draft?after=<last seq seen>`; the text chunks that come back are
 * appended to a draft bubble under the conversation, which goes away
 * when the turn's reply lands in the work log and the next turn's
 * request opens.
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

//: The one event that means "the draft grew" rather than "reload".
const STREAM = 'task.stream'

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
        .msg.draft { opacity: 0.8; border: 1px dashed var(--divider); }
        .msg.draft::after { content: '▍'; color: var(--accent); animation: blink 1s steps(2) infinite; }
        @keyframes blink { to { visibility: hidden; } }
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
    this.turns = []
    this.draft = { taskId: null, seq: 0, text: '' }
    this.pulls = Promise.resolve()
    try {
      this.unsubscribe = window.athanore.subscribe([...REFRESH_ON, STREAM], (event) => {
        if (event.run_id && event.run_id !== this.runId) return
        if (event.name === STREAM) this.pull()
        else this.load()
      })
    } catch (err) {
      this.fail(`live updates off: ${err.message}`)
    }
    this.load()
    this.pull()
  }

  disconnectedCallback() {
    this.unsubscribe?.()
  }

  fail(message) {
    this.state.textContent = message
    this.state.classList.toggle('bad', Boolean(message))
  }

  async call(path, init, params = {}) {
    const query = new URLSearchParams({ run_id: this.runId, ...params })
    const r = await window.athanore.fetch(`${path}?${query}`, init)
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

  /**
   * Pull the draft's next page. Pulls are chained so two `task.stream`
   * events in flight cannot append the same chunks twice, and a pull
   * that lands on a different task than the last one starts the draft
   * over — a new turn, a new reply.
   */
  pull() {
    this.pulls = this.pulls.then(async () => {
      const after = this.draft.seq
      let page
      try {
        page = await this.call('draft', undefined, { after: String(after) })
        if (page.task_id !== null && page.task_id !== this.draft.taskId) {
          // Another turn's task: its cursor starts at 0, so the page
          // that came back with the old task's cursor is not its start.
          this.draft = { taskId: page.task_id, seq: 0, text: '' }
          if (after !== 0) page = await this.call('draft', undefined, { after: '0' })
        }
      } catch (err) {
        this.fail(err.message)
        return
      }
      if (page.task_id === null) {
        this.draft = { taskId: null, seq: 0, text: '' }
      } else {
        this.draft.text += page.chunks.map((chunk) => chunk.text).join('')
        this.draft.seq = page.last_seq
      }
      this.paint()
    })
    return this.pulls
  }

  render(view) {
    this.view = view
    this.turns = view.turns
    const yours = view.pending !== null
    // The reply landed: it is in `turns` now, so the draft of it goes.
    if (yours) this.draft = { taskId: null, seq: 0, text: '' }
    this.paint()

    const over = view.run.status !== 'running' && view.run.status !== 'queued'
    this.box.disabled = over || !yours
    this.button.disabled = over || !yours
    this.state.classList.remove('bad')
    if (over) this.state.textContent = `run ${view.run.status}`
    else if (yours) this.state.textContent = ''
    else this.state.textContent = `${view.agent} is answering…`
    if (yours && !over) this.box.focus()
  }

  bubble(who, text, draft = false) {
    const div = document.createElement('div')
    div.className = `msg ${who === 'you' ? 'you' : 'them'}${draft ? ' draft' : ''}`
    const label = document.createElement('span')
    label.className = 'who'
    label.textContent = who
    div.append(label, text)
    return div
  }

  /** The conversation, then the draft if there is one. */
  paint() {
    const stuck = this.log.scrollTop + this.log.clientHeight >= this.log.scrollHeight - 8
    const bubbles = this.turns.map((turn) => this.bubble(turn.who, turn.text))
    if (this.draft.text) {
      bubbles.push(this.bubble(this.view?.agent ?? 'agent', this.draft.text, true))
    }
    this.log.replaceChildren(...bubbles)
    if (stuck) this.log.scrollTop = this.log.scrollHeight
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
