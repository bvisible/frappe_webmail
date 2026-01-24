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
        assetFileNames: 'frappe_webmail.[ext]'
      }
    },
    cssCodeSplit: false
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src')
    }
  },
  test: {
    globals: true,
    environment: 'happy-dom',
    setupFiles: ['./tests/setup.js'],
    include: ['tests/**/*.spec.js'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'html'],
      include: ['src/**/*.vue', 'src/**/*.js']
    }
  }
})
