import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: {
      // Keep local HTTP requests and WebSocket upgrades on the same origin.
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
        ws: true,
      },
      "/content": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
      "/img": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
})
