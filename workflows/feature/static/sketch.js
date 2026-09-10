/**
 * <athanore-sketch> — draw something and hand it to a run.
 *
 * The other half of the drop box: that one takes a file you already
 * have, this one makes one you do not. A wireframe, an arrow at the
 * thing that is wrong, a box round the odd part of the graph — sketched
 * on a tablet, saved into `.athanore/files/`, then named in a run's
 * description by the path the files pane copies.
 *
 * It declares **no routes**: `POST /api/plugins/feature/files` already
 * takes an upload and a canvas is a `Blob` with a name, so the whole
 * plugin is one `wf.panel(...)` line and this file.
 *
 * **Konva from a CDN, pinned exactly.** 09's escape hatch is one file of
 * browser JS with no build step, which is why `plugin_cdns` exists
 * (D211) — `athanore.toml` names jsDelivr and the CSP lets `script-src`
 * reach it. The version is pinned rather than ranged because a range
 * means the pane can change under you without a commit. Konva earns its
 * place by giving selection and resize handles, which are the tedious
 * part of a shape tool and the part that makes it feel like a tool.
 *
 * `connect-src` is still `'self'`, so nothing here may talk to jsDelivr
 * or anywhere else at runtime. Konva does not need to; a library that
 * did would not work, and that is the trade the setting makes.
 */

const KONVA = 'https://cdn.jsdelivr.net/npm/konva@10.5.0/konva.min.js'
/**
 * Subresource integrity for the file above — 187 kB, sha384.
 *
 * The version pin says *which* file; this says it is the same file. A
 * CDN is a party that can serve different bytes at the same URL, and the
 * one thing it must not be able to do is change what runs in the
 * operator's browser with `window.athanore` — the credential and `ops` —
 * in reach. With `integrity` the browser refuses a mismatch, so the
 * worst a compromised CDN can do here is break the pane.
 *
 * Regenerate with:
 *   curl -sL <the URL above> | openssl dgst -sha384 -binary | openssl base64 -A
 */
const KONVA_SRI =
  'sha384-5U3OBfaiWyVahgxO5gAPyCYQLRCh1teOWSUspbn2eNUbC8kq/3mdveFod0sZAhGt'

const TOOLS = ['select', 'box', 'ellipse', 'arrow', 'line', 'pen', 'text']
/**
 * The palette, six across. Row one is the greys from white to black, so
 * the extremes are where a hand expects them; the rest are three ramps.
 *
 * Black is in it because it is what a hand reaches for — but the canvas
 * is the app's dark background, so black draws black-on-near-black. It
 * is here for a sketch destined for somewhere lighter, not because it
 * will read on screen.
 */
const COLOURS = [
  '#ffffff', '#e8e6e3', '#a8a29e', '#57534e', '#292524', '#000000',
  '#fecaca', '#fca5a5', '#f87171', '#ef4444', '#dc2626', '#991b1b',
  '#fde68a', '#fcd34d', '#fbbf24', '#86efac', '#22c55e', '#15803d',
  '#bae6fd', '#7dd3fc', '#38bdf8', '#a5b4fc', '#c084fc', '#a855f7',
]
const SIZES = [2, 4, 8]

/** The upload cap, mirrored from `body_limit` so the message can say so. */
const LIMIT = 1024 * 1024

/** Load Konva once per document, however many panes ask for it. */
let loading = null
function konva() {
  if (window.Konva) return Promise.resolve(window.Konva)
  loading ??= new Promise((done, fail) => {
    const tag = document.createElement('script')
    tag.src = KONVA
    tag.integrity = KONVA_SRI
    // Required for `integrity` to be checked at all on a cross-origin
    // script: without it the response is opaque and the browser has
    // nothing to hash.
    tag.crossOrigin = 'anonymous'
    tag.addEventListener('load', () => done(window.Konva))
    tag.addEventListener('error', () =>
      fail(new Error(
        'could not load Konva. Either `plugin_cdns` does not name jsDelivr ' +
        '(athanore.toml), this machine has no route to it, or the file no ' +
        'longer matches KONVA_SRI.')))
    document.head.append(tag)
  })
  return loading
}

class AthanoreSketch extends HTMLElement {
  connectedCallback() {
    this.tool = 'box'
    this.colour = COLOURS[1]
    this.size = SIZES[1]

    this.attachShadow({ mode: 'open' })
    const theme = (window.athanore?.theme?.tokens) ?? {}
    const vars = ['--ath-bg', '--ath-surface', '--ath-border', '--ath-text',
      '--ath-muted', '--ath-accent', '--ath-status-ok', '--ath-status-bad']
      .map((t) => `${t}: ${theme[t] ?? 'inherit'}`).join(';')
    this.shadowRoot.innerHTML = `
      <style>
        :host { ${vars}; display: block; font: inherit; color: var(--ath-text); }
        .bar { display: flex; flex-wrap: wrap; gap: 8px; align-items: center;
               margin-bottom: 8px; }
        .stage { border: 1px solid var(--ath-border); border-radius: 8px;
                 background: var(--ath-bg); overflow: hidden;
                 /* Or a drag on a touchscreen scrolls the pane instead of
                    drawing, on the one device this pane is really for. */
                 touch-action: none; }
        button { font: inherit; color: var(--ath-text); background: var(--ath-surface);
                 border: 1px solid var(--ath-border); border-radius: 5px;
                 padding: 3px 8px; cursor: pointer; min-height: 24px; }
        button.save { color: var(--ath-accent); border-color: var(--ath-accent); }
        .picker { position: relative; display: inline-flex; }
        .current { width: 26px; height: 22px; padding: 0;
                   /* A ring in the border colour, so a white swatch and a
                      black one are both visible against the chrome. */
                   box-shadow: inset 0 0 0 1px var(--ath-border); }
        .grid { position: absolute; top: calc(100% + 4px); left: 0; z-index: 5;
                display: grid; grid-template-columns: repeat(6, 20px); gap: 4px;
                padding: 6px; background: var(--ath-surface);
                border: 1px solid var(--ath-border); border-radius: 8px;
                box-shadow: 0 6px 20px rgb(0 0 0 / 0.45); }
        .swatch { width: 20px; height: 20px; padding: 0; border-radius: 4px;
                  border: none; box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.18); }
        [aria-pressed="true"] { outline: 2px solid var(--ath-accent);
                                outline-offset: 1px; }
        .nib { width: 26px; }
        .muted { color: var(--ath-muted); }
        .bad { color: var(--ath-status-bad); }
        .ok { color: var(--ath-status-ok); }
        p { margin: 8px 0 0; }
      </style>
      <div class="bar">
        <span class="tools"></span>
        <span class="picker">
          <button class="current" type="button" aria-haspopup="true"
                  aria-expanded="false" aria-label="colour"></button>
          <div class="grid" role="listbox" aria-label="colours" hidden></div>
        </span>
        <span class="nibs"></span>
        <button class="del" type="button">delete</button>
        <button class="clear" type="button">clear</button>
        <button class="save" type="button">save to files</button>
      </div>
      <div class="stage"></div>
      <p class="muted">select to move and resize · saved into
        <code>.athanore/files/</code>, then copy its path from the files pane</p>
      <p class="note" hidden></p>`

    this.buttons('.tools', TOOLS, (v) => v, (v) => { this.tool = v; this.retool() })
    this.picker()
    this.buttons('.nibs', SIZES, (v) => String(v), (v) => { this.size = v }, 'nib')
    this.shadowRoot.querySelector('.del')
      .addEventListener('click', () => this.remove_())
    this.shadowRoot.querySelector('.clear')
      .addEventListener('click', () => this.clear())
    this.shadowRoot.querySelector('.save')
      .addEventListener('click', () => this.save())

    this.start().catch((err) => this.say(String(err.message ?? err), 'bad'))
  }

  /**
   * The colour trigger and its grid.
   *
   * A popover rather than a row because twenty-four swatches inline is a
   * toolbar that wraps to three lines on a tablet, which is the width
   * this pane is used at.
   */
  picker() {
    const trigger = this.shadowRoot.querySelector('.current')
    const grid = this.shadowRoot.querySelector('.grid')
    for (const value of COLOURS) {
      const swatch = document.createElement('button')
      swatch.type = 'button'
      swatch.className = 'swatch'
      swatch.style.background = value
      swatch.setAttribute('role', 'option')
      swatch.setAttribute('aria-label', value)
      swatch.addEventListener('click', () => {
        this.colour = value
        this.open(false)
        this.marks()
        trigger.focus()
      })
      grid.append(swatch)
    }
    trigger.addEventListener('click', () => this.open(grid.hidden))
    // `esc` from inside the grid closes it and nothing else: the app's
    // own `esc` would otherwise unwind a run selection behind an open
    // popover the operator was looking at (D209).
    this.shadowRoot.querySelector('.picker').addEventListener('keydown', (e) => {
      if (e.key !== 'Escape' || grid.hidden) return
      e.stopPropagation()
      this.open(false)
      trigger.focus()
    })
    // A click anywhere else closes it. `composedPath` because a click
    // inside this shadow root is retargeted to the host by the time the
    // document sees it — the same retargeting that made typing fire
    // hotkeys (D210).
    this.away = (e) => {
      if (!grid.hidden && !e.composedPath().includes(this.shadowRoot.querySelector('.picker'))) {
        this.open(false)
      }
    }
    document.addEventListener('pointerdown', this.away)
  }

  open(show) {
    const grid = this.shadowRoot.querySelector('.grid')
    grid.hidden = !show
    this.shadowRoot.querySelector('.current')
      .setAttribute('aria-expanded', String(show))
  }

  buttons(holder, values, label, pick, cls = 'tool') {
    const box = this.shadowRoot.querySelector(holder)
    for (const value of values) {
      const b = document.createElement('button')
      b.type = 'button'
      b.className = cls
      b.textContent = label(value)
      if (cls === 'swatch') b.style.background = value
      b.setAttribute('aria-label', `${cls} ${String(value)}`)
      b.addEventListener('click', () => {
        pick(value)
        this.marks()
      })
      box.append(b)
    }
  }

  marks() {
    for (const [sel, values, current] of [
      ['.tool', TOOLS, this.tool],
      ['.nib', SIZES, this.size],
    ]) {
      this.shadowRoot.querySelectorAll(sel).forEach((b, i) => {
        b.setAttribute('aria-pressed', String(values[i] === current))
      })
    }
    const trigger = this.shadowRoot.querySelector('.current')
    if (trigger !== null) {
      trigger.style.background = this.colour
      trigger.title = `colour ${this.colour}`
    }
    this.shadowRoot.querySelectorAll('.swatch').forEach((b, i) => {
      b.setAttribute('aria-selected', String(COLOURS[i] === this.colour))
    })
  }

  async start() {
    const Konva = await konva()
    this.Konva = Konva
    const host = this.shadowRoot.querySelector('.stage')
    const width = Math.max(1, host.clientWidth)
    const height = Math.max(240, Math.round(width * 0.6))
    host.style.height = `${height}px`

    this.stage = new Konva.Stage({ container: host, width, height })
    this.layer = new Konva.Layer()
    this.stage.add(this.layer)
    // Its own layer, so the handles are never in the exported image.
    this.overlay = new Konva.Layer()
    this.stage.add(this.overlay)
    this.transformer = new Konva.Transformer({ rotateEnabled: false })
    this.overlay.add(this.transformer)

    this.stage.on('mousedown touchstart', (e) => this.begin(e))
    this.stage.on('mousemove touchmove', () => this.extend())
    this.stage.on('mouseup touchend', () => { this.drawing = null })

    this.observer = new ResizeObserver(() => {
      const w = Math.max(1, host.clientWidth)
      this.stage.width(w)
      this.stage.height(Math.max(240, Math.round(w * 0.6)))
      host.style.height = `${this.stage.height()}px`
    })
    this.observer.observe(this)
    this.marks()
    this.retool()
  }

  disconnectedCallback() {
    if (this.away) document.removeEventListener('pointerdown', this.away)
    this.observer?.disconnect()
    this.stage?.destroy()
  }

  /** Only the select tool may grab a shape; the others draw over them. */
  retool() {
    const selecting = this.tool === 'select'
    for (const node of this.layer.getChildren()) node.draggable(selecting)
    if (!selecting) this.transformer.nodes([])
  }

  begin(event) {
    if (this.tool === 'select') {
      const hit = event.target === this.stage ? null : event.target
      this.transformer.nodes(hit === null ? [] : [hit])
      return
    }
    const { x, y } = this.stage.getPointerPosition()
    const common = { stroke: this.colour, strokeWidth: this.size, draggable: false }
    const K = this.Konva
    if (this.tool === 'text') {
      const text = window.prompt('text')
      if (text) {
        this.layer.add(new K.Text({
          x, y, text, fill: this.colour, fontSize: 12 + this.size * 3,
          fontFamily: 'ui-monospace, monospace', draggable: false,
        }))
      }
      return
    }
    const made =
      this.tool === 'box' ? new K.Rect({ ...common, x, y, width: 0, height: 0 })
      : this.tool === 'ellipse' ? new K.Ellipse({ ...common, x, y, radiusX: 0, radiusY: 0 })
      : this.tool === 'arrow' ? new K.Arrow({ ...common, points: [x, y, x, y],
          fill: this.colour, pointerLength: 6 + this.size, pointerWidth: 6 + this.size })
      : this.tool === 'line' ? new K.Line({ ...common, points: [x, y, x, y] })
      : new K.Line({ ...common, points: [x, y], lineCap: 'round', lineJoin: 'round',
          tension: 0.3 })
    this.layer.add(made)
    this.drawing = { node: made, from: { x, y } }
  }

  extend() {
    if (!this.drawing) return
    const { node, from } = this.drawing
    const { x, y } = this.stage.getPointerPosition()
    if (this.tool === 'box') {
      node.position({ x: Math.min(from.x, x), y: Math.min(from.y, y) })
      node.size({ width: Math.abs(x - from.x), height: Math.abs(y - from.y) })
    } else if (this.tool === 'ellipse') {
      node.radiusX(Math.abs(x - from.x))
      node.radiusY(Math.abs(y - from.y))
    } else if (this.tool === 'pen') {
      node.points([...node.points(), x, y])
    } else {
      node.points([from.x, from.y, x, y])
    }
  }

  remove_() {
    for (const node of this.transformer.nodes()) node.destroy()
    this.transformer.nodes([])
  }

  clear() {
    this.transformer.nodes([])
    this.layer.destroyChildren()
  }

  say(message, kind) {
    const note = this.shadowRoot.querySelector('.note')
    note.textContent = message
    note.className = `note ${kind}`
    note.hidden = !message
  }

  async save() {
    if (!this.layer || this.layer.getChildren().length === 0) {
      this.say('nothing drawn yet', 'muted')
      return
    }
    // Handles are on their own layer and `toCanvas` is asked for the
    // drawing one, so a selection never ends up in the file.
    const drawn = this.layer.toCanvas({ pixelRatio: 2 })
    // A transparent PNG on a dark theme is a black rectangle to whatever
    // opens it next, so the background is painted in first.
    const flat = document.createElement('canvas')
    flat.width = drawn.width
    flat.height = drawn.height
    const context = flat.getContext('2d')
    context.fillStyle =
      getComputedStyle(this.shadowRoot.querySelector('.stage')).backgroundColor || '#111'
    context.fillRect(0, 0, flat.width, flat.height)
    context.drawImage(drawn, 0, 0)

    const blob = await new Promise((done) => flat.toBlob(done, 'image/png'))
    if (blob === null) {
      this.say('the browser would not export the canvas', 'bad')
      return
    }
    if (blob.size > LIMIT) {
      this.say(`that sketch is ${(blob.size / 1024 / 1024).toFixed(1)} MB, over the ` +
        '1 MiB body limit — simplify it or raise ATHANORE_BODY_LIMIT', 'bad')
      return
    }
    const stamp = new Date().toISOString().slice(0, 16).replace(/[:T]/g, '-')
    const body = new FormData()
    body.append('file', blob, `sketch-${stamp}.png`)
    try {
      const r = await window.athanore.fetch('files', { method: 'POST', body })
      if (!r.ok) throw new Error(`the drop box answered ${r.status}`)
      this.say(`saved ${(await r.json()).path}`, 'ok')
    } catch (err) {
      this.say(String(err.message ?? err), 'bad')
    }
  }
}

customElements.define('athanore-sketch', AthanoreSketch)
