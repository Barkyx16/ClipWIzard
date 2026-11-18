import { defineConfig, devices } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

// End-to-end tests drive the real backend (serving the built UI) in a browser.
// Run: npm run build && npm run e2e
const python = process.env.E2E_PYTHON ?? "../.venv/bin/python";
const port = Number(process.env.E2E_PORT ?? 8765);
const dataDir = process.env.E2E_DATA_DIR ?? mkdtempSync(join(tmpdir(), "clipwizard-e2e-"));
process.env.E2E_DATA_DIR = dataDir;
process.env.E2E_PYTHON = python;

export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  expect: { timeout: 30_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["github"]] : "list",
  globalSetup: "./e2e/global-setup.ts",
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    trace: "off",
    ...devices["Desktop Chrome"],
    viewport: { width: 1440, height: 1000 },
  },
  webServer: {
    command: `${python} -m uvicorn app.main:app --host 127.0.0.1 --port ${port}`,
    cwd: "../backend",
    url: `http://127.0.0.1:${port}/api/health`,
    reuseExistingServer: false,
    timeout: 60_000,
    env: {
      CLIPWIZARD_DATA_DIR: dataDir,
      CLIPWIZARD_SKIP_DOTENV: "1",
      CLIPWIZARD_FAKE_TRANSCRIBE: "1",
      CLIPWIZARD_RATE_LIMIT_PER_MIN: "0",
      CLIPWIZARD_RATE_LIMIT_PER_HOUR: "0",
      ANTHROPIC_API_KEY: "",
    },
  },
});
