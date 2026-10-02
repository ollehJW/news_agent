import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
const proxy = { '/api': { target: process.env.BACKEND_ORIGIN || 'http://127.0.0.1:9801', changeOrigin: true, proxyTimeout: 140000 } };
export default defineConfig({ base: './', plugins: [react()], server: { proxy }, preview: { proxy } });
