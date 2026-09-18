import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

function publicTargetOnly(req) {
  const path = new URL(req.url, 'http://target').pathname;
  const allowed =
    req.method === 'GET'
      ? /^\/api\/(health|metrics|jobs|probe)$/.test(path)
      : req.method === 'POST' && /^\/api\/(login|jobs)$/.test(path);
  if (!allowed) return false;
}

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5174,
    proxy: {
      '/api': {
        target: process.env.TARGET_URL || 'http://localhost:8080',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
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
