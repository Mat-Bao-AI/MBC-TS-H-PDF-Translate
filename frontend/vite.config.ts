import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/api': 'http://127.0.0.1:8000', '/health': 'http://127.0.0.1:8000' } },
  build: { outDir: 'dist', chunkSizeWarningLimit: 1200 },
  test: { environment: 'jsdom', setupFiles: ['./src/setupTests.ts'], include: ['src/**/*.test.{ts,tsx}'] },
});
