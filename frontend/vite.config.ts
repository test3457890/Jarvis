import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  base: '/',
  build: {
    outDir: '../jarvis/static/cc',
    emptyOutDir: true,
    assetsDir: 'assets',
    rollupOptions: {
      output: {
        entryFileNames: 'assets/cc-app.js',
        chunkFileNames: 'assets/cc-[name].js',
        assetFileNames: 'assets/cc-[name][extname]',
      },
    },
  },
  experimental: {
    renderBuiltUrl(filename) {
      if (filename.startsWith('assets/')) {
        return '/cc-assets/' + filename.slice('assets/'.length);
      }
      return '/' + filename;
    },
  },
});
