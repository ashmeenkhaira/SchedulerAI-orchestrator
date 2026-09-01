import path from 'path';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

// Gemini is called server-side now (see backend/app/gemini_service.py), so
// no API key needs to reach the client bundle. VITE_API_BASE_URL /
// VITE_WEBSOCKET_URL (read via import.meta.env in constants.ts) point the
// frontend at the deployed backend.
export default defineConfig({
  server: {
    port: 3000,
    host: '0.0.0.0',
    strictPort: true,  // fail loudly if port 3000 is already in use
  },
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, '.'),
    }
  }
});
