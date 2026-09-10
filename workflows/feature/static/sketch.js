/**
 * <athanore-sketch> — draw something and hand it to a run.
 *
 * The other half of the drop box: that one takes a file you already
 * have, this one makes one you do not. A wireframe, an arrow pointing at
 * the thing that is wrong, a box round the bit of the graph that looks
 * odd — sketched on a tablet and saved into `.athanore/files/`, then
 * named in a run's description by the path the files pane copies.
 *
 * It declares **no routes of its own**: `POST /api/plugins/feature/files`
 * already takes an upload, and a canvas is just a `Blob` with a name. The
 * whole plugin is this element and one `wf.panel(...)` line.
 *
 * Strokes are kept as points and the canvas is redrawn from them, rather
 * than the canvas being the state. That is what makes undo one `pop()`
 * and a resize a redraw instead of a stretched bitmap — a sketch is a
 * list of gestures, and treating it as pixels loses that the moment the
 * pane changes width.
 */

const COLOURS = ['#e8e6e3', '#7dd3fc', '#fca5a5', '#fcd34d', '#86efac']
const SIZES = [2, 4, 8, 16]

/** The upload cap, mirrored from `body_limit` so the message can say so. */
const LIMIT = 1024 * 1024

class AthanoreSketch extends HTMLElement {
  connectedCallback() {
    this.strokes = []
    this.stroke = null
    this.colour = COLOURS[0]
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
        canvas { display: block; width: 100%; border: 1px solid var(--ath-border);
                 border-radius: 8px; background: var(--ath-bg);
                 /* Without this a drag on a touchscreen scrolls the pane
                    instead of drawing, which is the one device this pane
                    is really for. */
                 touch-action: none; cursor: crosshair; }
        button { font: inherit; color: var(--ath-text); background: var(--ath-surface);
                 border: 1px solid var(--ath-border); border-radius: 5px;
                 padding: 3px 8px; cursor: pointer; min-height: 24px; }
        button.save { color: var(--ath-accent); border-color: var(--ath-accent); }
        .swatch { width: 20px; height: 20px; padding: 0; border-radius: 50%; }
        .swatch[aria-pressed="true"], .nib[aria-pressed="true"] {
          outline: 2px solid var(--ath-accent); outline-offset: 1px; }
        .nib { width: 26px; }
        .muted { color: var(--ath-muted); }
        .bad { color: var(--ath-status-bad); }
        .ok { color: var(--ath-status-ok); }
        p { margin: 8px 0 0; }
      </style>
      <div class="bar">
        <span class="colours"></span>
        <span class="nibs"></span>
        <button class="undo" type="button">undo</button>
        <button class="clear" type="button">clear</button>
        <button class="save" type="button">save to files</button>
      </div>
      <canvas></canvas>
      <p class="muted">saved into <code>.athanore/files/</code> — copy its
        path from the files pane and name it in a run's description</p>
      <p class="note" hidden></p>`

    const bar = this.shadowRoot
    for (const [holder, values, make] of [
      ['.colours', COLOURS, (v) => {
        const b = document.createElement('button')
        b.className = 'swatch'
        b.style.background = v
        b.setAttribute('aria-label', `colour ${v}`)
        return b
      }],
      ['.nibs', SIZES, (v) => {
        const b = document.createElement('button')
        b.className = 'nib'
        b.textContent = String(v)
        b.setAttribute('aria-label', `${v} pixel nib`)
        return b
      }],
    ]) {
      const box = bar.querySelector(holder)
      for (const value of values) {
        const button = make(value)
        button.type = 'button'
        button.addEventListener('click', () => {
          if (holder === '.colours') this.colour = value
          else this.size = value
          this.marks()
        })
        box.append(button)
      }
    }
    bar.querySelector('.undo').addEventListener('click', () => {
      this.strokes.pop()
      this.redraw()
    })
    bar.querySelector('.clear').addEventListener('click', () => {
      this.strokes = []
      this.redraw()
    })
    bar.querySelector('.save').addEventListener('click', () => this.save())
    this.marks()

    this.canvas = bar.querySelector('canvas')
    this.canvas.addEventListener('pointerdown', (e) => this.begin(e))
    this.canvas.addEventListener('pointermove', (e) => this.extend(e))
    for (const done of ['pointerup', 'pointercancel', 'pointerleave']) {
      this.canvas.addEventListener(done, () => { this.stroke = null })
    }
    this.observer = new ResizeObserver(() => this.fit())
    this.observer.observe(this)
    this.fit()
  }

  disconnectedCallback() {
    this.observer?.disconnect()
  }

  /** Show which colour and nib are current. */
  marks() {
    for (const [sel, values, current] of [
      ['.swatch', COLOURS, this.colour],
      ['.nib', SIZES, this.size],
    ]) {
      this.shadowRoot.querySelectorAll(sel).forEach((b, i) => {
        b.setAttribute('aria-pressed', String(values[i] === current))
      })
    }
  }

  /**
   * Size the backing store to the pane, in device pixels, and redraw.
   *
   * The CSS width is 100%, so the *drawing* size has to be set in
   * `devicePixelRatio` units or a stylus line comes out soft on exactly
   * the screens people sketch on.
   */
  fit() {
    const ratio = window.devicePixelRatio || 1
    const width = Math.max(1, Math.floor(this.canvas.clientWidth))
    const height = Math.max(220, Math.floor(width * 0.6))
    this.canvas.style.height = `${height}px`
    this.canvas.width = Math.floor(width * ratio)
    this.canvas.height = Math.floor(height * ratio)
    const context = this.canvas.getContext('2d')
    context.setTransform(ratio, 0, 0, ratio, 0, 0)
    this.redraw()
  }

  /** Canvas coordinates for a pointer event, in CSS pixels. */
  at(event) {
    const box = this.canvas.getBoundingClientRect()
    return { x: event.clientX - box.left, y: event.clientY - box.top }
  }

  begin(event) {
    // Only the primary contact draws: a second finger on a tablet is a
    // gesture, not a second line.
    if (!event.isPrimary) return
    this.canvas.setPointerCapture(event.pointerId)
    this.stroke = { colour: this.colour, size: this.size, points: [this.at(event)] }
    this.strokes.push(this.stroke)
    this.redraw()
  }

  extend(event) {
    if (this.stroke === null || !event.isPrimary) return
    this.stroke.points.push(this.at(event))
    this.redraw()
  }

  redraw() {
    const context = this.canvas.getContext('2d')
    const ratio = window.devicePixelRatio || 1
    context.clearRect(0, 0, this.canvas.width / ratio, this.canvas.height / ratio)
    context.lineCap = context.lineJoin = 'round'
    for (const stroke of this.strokes) {
      context.strokeStyle = stroke.colour
      context.lineWidth = stroke.size
      context.beginPath()
      const [first, ...rest] = stroke.points
      context.moveTo(first.x, first.y)
      // A single tap is a dot, not nothing: a line to itself with a
      // round cap draws the nib.
      if (rest.length === 0) context.lineTo(first.x, first.y)
      for (const point of rest) context.lineTo(point.x, point.y)
      context.stroke()
    }
  }

  say(message, kind) {
    const note = this.shadowRoot.querySelector('.note')
    note.textContent = message
    note.className = `note ${kind}`
    note.hidden = !message
  }

  async save() {
    if (this.strokes.length === 0) {
      this.say('nothing drawn yet', 'muted')
      return
    }
    // A transparent PNG on a dark theme is a black rectangle to whatever
    // opens it next, so the background is painted in before the export.
    const flat = document.createElement('canvas')
    flat.width = this.canvas.width
    flat.height = this.canvas.height
    const context = flat.getContext('2d')
    context.fillStyle = getComputedStyle(this.canvas).backgroundColor || '#111'
    context.fillRect(0, 0, flat.width, flat.height)
    context.drawImage(this.canvas, 0, 0)

    const blob = await new Promise((done) => flat.toBlob(done, 'image/png'))
    if (blob === null) {
      this.say('the browser would not export the canvas', 'bad')
      return
    }
    if (blob.size > LIMIT) {
      this.say(`that sketch is ${(blob.size / 1024 / 1024).toFixed(1)} MB, over the ` +
        '1 MiB body limit — clear some strokes or raise ATHANORE_BODY_LIMIT', 'bad')
      return
    }
    const stamp = new Date().toISOString().slice(0, 16).replace(/[:T]/g, '-')
    const body = new FormData()
    body.append('file', blob, `sketch-${stamp}.png`)
    try {
      const r = await window.athanore.fetch('files', { method: 'POST', body })
      if (!r.ok) throw new Error(`the drop box answered ${r.status}`)
      const saved = await r.json()
      this.say(`saved ${saved.path}`, 'ok')
    } catch (err) {
      this.say(String(err.message ?? err), 'bad')
    }
  }
}

customElements.define('athanore-sketch', AthanoreSketch)
