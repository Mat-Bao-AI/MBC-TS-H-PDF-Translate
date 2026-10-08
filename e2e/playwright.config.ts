import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: 'tests',
  timeout: 10 * 60 * 1000,
  expect: { timeout: 15_000 },
  workers: 1,
  use: { baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:18082', trace: 'retain-on-failure' },
});
