/**
 * The end-to-end suite's configuration (`docs/v1/17-serial-task-plan.md`
 * § T068a, 13 §Pyramid).
 *
 * **Chromium only.** One engine, in the dev image and on the runner, is
 * what T068a asks for: the SPA is an operator tool served on loopback,
 * and a browser matrix would be a matrix of the same assertions.
 *
 * **No `webServer`.** Each test starts an `athanore serve` of its own on
 * an ephemeral port over a temporary root (`e2e/support/server.ts`),
 * because two of these specs need a machine nobody else is using: the
 * queue specs fill the single worker slot deliberately, and the
 * connection spec kills the process and starts it again.
 *
 * **The browser comes from the image.** `docker/dev/Dockerfile` installs
 * the chromium of `PLAYWRIGHT_VERSION` into `PLAYWRIGHT_BROWSERS_PATH`
 * (D68), and `@playwright/test` is pinned to that same version so the
 * revision the runner downloads and the revision the image ships are one
 * browser.
 */
import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  // Each test owns its server, so nothing here shares state; the cap is
  // about the machine rather than about correctness — every worker runs
  // a python server, a chromium and an agent subprocess of its own.
  fullyParallel: true,
  workers: 2,
  // A failure that does not reproduce is worth knowing about rather than
  // hiding: a retried test is reported as flaky, and the gate stays
  // green only for the specs that pass on their own terms.
  retries: 1,
  // Generous, because a test includes starting a server: the assertions
  // inside it have their own, tighter deadline.
  timeout: 120_000,
  expect: { timeout: 15_000 },
  forbidOnly: true,
  reporter: [['list'], ['html', { outputFolder: 'playwright-report', open: 'never' }]],
  use: {
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
})
