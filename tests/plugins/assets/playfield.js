// The one asset the fixture workflow ships (09 §Escape hatch).
//
// A `custom` panel renders `<gd-playfield run-id=… task-id=… node=…>`
// inside a thin React wrapper, and the host puts `window.athanore` — and
// the same object on the element itself — in place before the element is
// connected. So `connectedCallback` is where both may be read, and this
// element reads them there: `fetch` for its own route, `subscribe` for
// the events that invalidate it, `theme` for the tokens that let it look
// like the rest of the application inside a shadow root.
//
// Nothing else crosses. There is no import, no framework and no second
// global: an asset is an ES module the SPA injects once, and this is what
// one looks like.

class Playfield extends HTMLElement {
  connectedCallback() {
    // The element's own binding first — it is bound to *this* element's
    // workflow, where `window.athanore` is bound to whichever mounted
    // most recently (09 §Escape hatch, D183).
    this.host = this.athanore || window.athanore;
    this.root = this.attachShadow({ mode: "open" });
    this.root.innerHTML = `<style>
      :host { display: block; font: inherit; color: var(--fg, inherit); }
      p { margin: 0; }
    </style><p data-role="word">…</p>`;
    this.applyTheme();
    this.unsubscribe = this.host.subscribe(["task.*", "log.appended"], () =>
      this.load(),
    );
    this.load();
  }

  disconnectedCallback() {
    if (this.unsubscribe) this.unsubscribe();
  }

  applyTheme() {
    // `theme.tokens` are CSS custom properties, and setting them on the
    // shadow host is what pierces the boundary they would not cross.
    const tokens = (this.host.theme && this.host.theme.tokens) || {};
    for (const [name, value] of Object.entries(tokens)) {
      this.style.setProperty(name, value);
    }
  }

  async load() {
    const runId = this.getAttribute("run-id");
    if (!runId) return;
    // Relative, and therefore under `/api/plugins/gamedev/`. An absolute
    // URL or a `..` is a TypeError before a request is made.
    const response = await this.host.fetch(
      `round?run_id=${encodeURIComponent(runId)}`,
    );
    const round = await response.json();
    this.root.querySelector('[data-role="word"]').textContent =
      round.Word ?? "—";
  }
}

customElements.define("gd-playfield", Playfield);
