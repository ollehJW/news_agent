import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
const proxy = { '/api': { target: 'http://127.0.0.1:6112', changeOrigin: true, proxyTimeout: 140000 } };
export default defineConfig({ plugins: [react()], server: { proxy }, preview: { proxy } });
