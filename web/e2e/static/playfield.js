/**
 * `<e2e-playfield>`: the plugin web component `plugin.spec.ts` drives
 * (`docs/v1/09-plugins.md` §Escape hatch).
 *
 * A fixture, and deliberately a plausible one. It is written the way a
 * plugin author would write one — a plain custom element, no framework,
 * no import — and it uses each of the three capabilities
 * `window.athanore` grants and nothing else:
 *
 * - `fetch('/state?run_id=…')` reaches the workflow's own route. The
 *   path is relative, so the host resolves it under
 *   `/api/plugins/plugged/` and puts the operator credential on it.
 * - `subscribe(['log.appended'], …)` reads the tab's one event stream,
 *   filtered. The element counts what arrives, which is what the spec
 *   asserts on after it appends a note to the run's work log.
 * - `theme.tokens` colours the element from the design system, which is
 *   what makes it look like part of the app inside a pane it draws
 *   itself.
 *
 * It is served by the Athanore server under the policy of 12 §Plugins,
 * so there is no import, no inline `<style>` in a document it does not
 * own, and nothing loaded from a third origin.
 */

class Playfield extends HTMLElement {
  /** The bridge this element uses; the host also puts one on `this`. */
  #athanore = null

  /** What `subscribe` returns, called on the way out. */
  #unsubscribe = null

  /** How many events have arrived since this element was connected. */
  #events = 0

  /** What the route answered with, or the refusal it answered with. */
  #state = null
  #error = null

  connectedCallback() {
    // `this.athanore` is the bridge bound to this element's own
    // workflow; `window.athanore` is the same three capabilities and is
    // what 09 names. Either is correct here — the element prefers its
    // own, which is what a plugin sharing a page with another should do.
    this.#athanore = this.athanore ?? window.athanore
    this.#paint()
    this.#unsubscribe = this.#athanore.subscribe(['log.appended'], () => {
      this.#events += 1
      this.#paint()
    })
    void this.#load()
  }

  disconnectedCallback() {
    this.#unsubscribe?.()
    this.#unsubscribe = null
  }

  async #load() {
    const runId = this.getAttribute('run-id')
    if (runId === null) {
      this.#error = 'no run in scope'
      this.#paint()
      return
    }
    try {
      const response = await this.#athanore.fetch(
        `/state?run_id=${encodeURIComponent(runId)}`,
      )
      if (!response.ok) {
        this.#error = `the route answered ${response.status}`
      } else {
        this.#state = await response.json()
      }
    } catch (error) {
      this.#error = String(error)
    }
    this.#paint()
  }

  #paint() {
    const tokens = this.#athanore?.theme.tokens ?? {}
    this.replaceChildren(
      this.#line('playfield-word', this.#error ?? this.#state?.word ?? 'loading…', {
        color: tokens['--color-accent-300'] ?? '',
      }),
      this.#line('playfield-run', this.#state?.run_id ?? ''),
      this.#line('playfield-events', String(this.#events)),
    )
  }

  /** One `<p data-testid=…>`, styled from the tokens and nothing else. */
  #line(testid, text, style = {}) {
    const line = document.createElement('p')
    line.dataset.testid = testid
    line.textContent = text
    Object.assign(line.style, style)
    return line
  }
}

customElements.define('e2e-playfield', Playfield)
