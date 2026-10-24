import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [sveltekit()],
  envDir: '../',
  server: {
    port: 5173,
    host: true
  }
});
