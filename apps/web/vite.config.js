import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// The browser can observe/use the demo app; fault administration is server-only.
function publicTargetOnly(req) {
  const path = new URL(req.url, 'http://target').pathname;
  const allowed =
    req.method === 'GET'
      ? /^\/target\/(health|metrics|jobs|probe)$/.test(path)
      : req.method === 'POST' && /^\/target\/(login|jobs)$/.test(path);
  if (!allowed) return false;
}

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': {
        target: process.env.CONTROL_URL || 'http://localhost:8081',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
      '/target': {
        target: process.env.TARGET_URL || 'http://localhost:8080',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/target/, ''),
        bypass: publicTargetOnly,
        configure: (proxy) =>
          proxy.on('proxyReq', (request) => {
            for (const header of request.getHeaderNames()) {
              if (header.startsWith('x-sealed-')) request.removeHeader(header);
            }
          }),
      },
    },
  },
});
