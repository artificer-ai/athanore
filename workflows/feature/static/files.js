/**
 * <athanore-files> — the drop box pane.
 *
 * 09 §Escape hatch: the SPA injects this module once, the `custom` panel
 * renders the tag, and the element gets `window.athanore` — `fetch`
 * bound to `/api/plugins/feature/` and carrying auth, `subscribe` for
 * the event feed, and `theme.tokens` so a shadow root can look like the
 * rest of the app instead of like a form from 1997.
 *
 * No framework and no build step on purpose: this is dev machinery that
 * has to stay readable next to the Python it serves, and one file that
 * the browser runs as-is has no toolchain to keep in step with `web/`'s.
 */

const TOKENS = [
  '--ath-bg', '--ath-surface', '--ath-border', '--ath-text',
  '--ath-muted', '--ath-accent', '--ath-status-ok', '--ath-status-bad',
]

/** Bytes as something a person reads at a glance. */
function size(n) {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} kB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

/** A clipboard icon and a tick, as inline SVG inheriting `currentColor`. */
const COPY_ICON =
  '<svg width="13" height="13" viewBox="0 0 16 16" fill="none" ' +
  'stroke="currentColor" stroke-width="1.5" aria-hidden="true">' +
  '<rect x="5.5" y="5.5" width="9" height="9" rx="1.5"/>' +
  '<path d="M10.5 3.5v-1a1 1 0 0 0-1-1h-7a1 1 0 0 0-1 1v7a1 1 0 0 0 1 1h1"/></svg>'
const DONE_ICON =
  '<svg width="13" height="13" viewBox="0 0 16 16" fill="none" ' +
  'stroke="currentColor" stroke-width="1.8" aria-hidden="true">' +
  '<path d="M3 8.5l3.5 3.5L13 5"/></svg>'

/**
 * Put `text` on the clipboard, and say whether it landed.
 *
 * `navigator.clipboard` exists only in a **secure context** — HTTPS, or
 * localhost. This pane's whole reason for existing is being reached from
 * a phone at `http://<lan-ip>:4002`, which is neither, so on the device
 * that needs it most the modern API is simply `undefined`.
 *
 * The fallback is the deprecated `document.execCommand('copy')`, which
 * still works over plain HTTP everywhere that matters. The textarea goes
 * in the *document*, not the shadow root: the selection APIs the command
 * reads operate on the document's selection, and a node inside a closed
 * subtree is not reliably part of it.
 */
async function copyText(text) {
  try {
    if (window.isSecureContext && navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    // fall through — a permissions refusal is not worth a message of its
    // own when there is a second way to try.
  }
  const area = document.createElement('textarea')
  area.value = text
  area.setAttribute('readonly', '')
  area.style.cssText = 'position:fixed;top:-1000px;opacity:0'
  document.body.append(area)
  area.select()
  let ok = false
  try {
    ok = document.execCommand('copy')
  } catch {
    ok = false
  }
  area.remove()
  return ok
}

class AthanoreFiles extends HTMLElement {
  connectedCallback() {
    this.attachShadow({ mode: 'open' })
    // Pierce the shadow boundary with the host's own tokens, so this
    // pane follows the theme and the font-size chooser (T081) rather
    // than pinning its own sizes.
    const theme = (window.athanore?.theme?.tokens) ?? {}
    const vars = TOKENS.map((t) => `${t}: ${theme[t] ?? 'inherit'}`).join(';')
    this.shadowRoot.innerHTML = `
      <style>
        :host { ${vars}; display: block; font: inherit; color: var(--ath-text); }
        .drop { border: 1px dashed var(--ath-border); border-radius: 8px;
                padding: 18px; text-align: center; cursor: pointer;
                background: var(--ath-surface); }
        .drop[data-over="1"] { border-color: var(--ath-accent); }
        .row { display: flex; gap: 10px; align-items: baseline;
               padding: 5px 0; border-bottom: 1px solid var(--ath-border); }
        .name { flex: 1; overflow-wrap: anywhere; }
        .muted { color: var(--ath-muted); }
        .bad { color: var(--ath-status-bad); }
        button { font: inherit; color: var(--ath-accent); background: none;
                 border: none; cursor: pointer; padding: 0; }
        button.link { text-align: left; text-decoration: underline; }
        button.icon { display: inline-flex; align-items: center;
                      color: var(--ath-muted); }
        button.icon:hover { color: var(--ath-accent); }
        a { color: var(--ath-accent); }
        ul { list-style: none; margin: 12px 0 0; padding: 0; }
      </style>
      <div class="drop" part="drop"><strong>drop a file</strong>
        <div class="muted">or click to choose — 1 MiB max, lands in
        <code>.athanore/files/</code></div>
        <input type="file" hidden multiple>
      </div>
      <p class="bad" hidden></p>
      <ul></ul>`

    const drop = this.shadowRoot.querySelector('.drop')
    const input = this.shadowRoot.querySelector('input')
    drop.addEventListener('click', () => input.click())
    input.addEventListener('change', () => this.send(input.files))
    drop.addEventListener('dragover', (e) => {
      e.preventDefault()
      drop.dataset.over = '1'
    })
    drop.addEventListener('dragleave', () => { drop.dataset.over = '0' })
    drop.addEventListener('drop', (e) => {
      e.preventDefault()
      drop.dataset.over = '0'
      this.send(e.dataTransfer.files)
    })
    this.load()
  }

  fail(message) {
    const p = this.shadowRoot.querySelector('p')
    p.textContent = message
    p.hidden = message === ''
  }

  async load() {
    try {
      const r = await window.athanore.fetch('files')
      if (!r.ok) throw new Error(`the drop box answered ${r.status}`)
      this.draw(await r.json())
      this.fail('')
    } catch (err) {
      this.fail(String(err.message ?? err))
    }
  }

  async send(files) {
    for (const file of files) {
      const body = new FormData()
      body.append('file', file, file.name)
      try {
        const r = await window.athanore.fetch('files', { method: 'POST', body })
        if (!r.ok) {
          // 413 is the body cap, and it is the one failure worth naming
          // precisely: it is a setting, not a mistake.
          const why = r.status === 413
            ? `${file.name} is over the 1 MiB body limit (ATHANORE_BODY_LIMIT)`
            : `${file.name} was refused: ${r.status}`
          throw new Error(why)
        }
        this.fail('')
      } catch (err) {
        this.fail(String(err.message ?? err))
      }
    }
    await this.load()
  }

  /**
   * Fetch the bytes with auth, then hand them to the browser as a blob.
   *
   * A plain `<a href="/api/plugins/feature/files/x">` is a *navigation*,
   * and a navigation carries no `Authorization` header — so on any bind
   * that is not loopback it 401s. The same shape as `EventSource`, which
   * the API answers with an `access_token` query parameter; but 12 §Auth
   * sanctions that for `GET /api/events` and nothing else, and putting a
   * token in a URL here would spread it into history and referrers for a
   * problem that has a local answer.
   *
   * `window.athanore.fetch` already carries the credential, so the bytes
   * come back over an ordinary authenticated request and only *then*
   * become something the browser saves. The object URL is revoked on the
   * next tick: keeping it alive pins the whole file in memory.
   */
  async save(name) {
    try {
      const r = await window.athanore.fetch(`files/${encodeURIComponent(name)}`)
      if (!r.ok) throw new Error(`could not download ${name}: ${r.status}`)
      const url = URL.createObjectURL(await r.blob())
      const a = document.createElement('a')
      a.href = url
      a.download = name
      a.click()
      setTimeout(() => URL.revokeObjectURL(url), 0)
      this.fail('')
    } catch (err) {
      this.fail(String(err.message ?? err))
    }
  }

  async remove(name) {
    const r = await window.athanore.fetch(`files/${encodeURIComponent(name)}`,
      { method: 'DELETE' })
    if (!r.ok) this.fail(`could not delete ${name}: ${r.status}`)
    await this.load()
  }

  draw(entries) {
    const list = this.shadowRoot.querySelector('ul')
    list.replaceChildren()
    if (entries.length === 0) {
      const li = document.createElement('li')
      li.className = 'muted'
      li.textContent = 'nothing dropped yet'
      list.append(li)
      return
    }
    for (const entry of entries) {
      const li = document.createElement('li')
      li.className = 'row'
      // A button, not a link: the download goes through
      // `window.athanore.fetch` so it carries auth (see `save`), and an
      // <a href> here would be an unauthenticated navigation that 401s
      // on every bind but loopback.
      const a = document.createElement('button')
      a.textContent = entry.name
      a.className = 'name link'
      a.addEventListener('click', () => this.save(entry.name))
      const when = document.createElement('span')
      when.className = 'muted'
      when.textContent = `${size(entry.bytes)} · ` +
        new Date(entry.modified * 1000).toLocaleString()
      const copy = document.createElement('button')
      copy.className = 'icon'
      copy.innerHTML = COPY_ICON
      copy.title = `copy ${entry.path}`
      copy.setAttribute('aria-label', `copy the path of ${entry.name}`)
      copy.addEventListener('click', async () => {
        const ok = await copyText(entry.path)
        if (!ok) {
          this.fail(`could not reach the clipboard — the path is ${entry.path}`)
          return
        }
        // The tick is the only feedback: a toast for a copy is noise, and
        // the operator is already looking at the thing they clicked.
        copy.innerHTML = DONE_ICON
        setTimeout(() => { copy.innerHTML = COPY_ICON }, 1200)
        this.fail('')
      })
      const del = document.createElement('button')
      del.textContent = 'delete'
      del.addEventListener('click', () => this.remove(entry.name))
      li.append(a, when, copy, del)
      list.append(li)
    }
  }
}

customElements.define('athanore-files', AthanoreFiles)
