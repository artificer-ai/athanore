/**
 * Build-time constants `vite.config.ts` substitutes with `define`.
 *
 * The app's version is the distribution's: `pyproject.toml`'s
 * `[project] version`, read at build time so the header cannot drift
 * from the wheel it was built into (10 §Layout).
 */
declare const __APP_VERSION__: string
