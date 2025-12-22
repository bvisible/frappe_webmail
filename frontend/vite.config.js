import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'

export default defineConfig({
  plugins: [vue()],
  build: {
    outDir: '../frappe_webmail/public/js',
    emptyOutDir: false,
    lib: {
      entry: path.resolve(__dirname, 'src/main.js'),
      name: 'FrappeWebmail',
      fileName: 'frappe_webmail.bundle',
      formats: ['iife']
    },
    rollupOptions: {
      external: ['vue'],
      output: {
        globals: {
          vue: 'Vue'
        },
        assetFileNames: (assetInfo) => {
          if (assetInfo.name === 'style.css') {
            return '../css/frappe_webmail.css'
          }
          return assetInfo.name
        }
      }
    }
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src')
    }
  }
})
