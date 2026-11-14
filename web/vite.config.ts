import { defineConfig } from 'vite';

export default defineConfig({
  base: './',
  build: {
    target: 'es2022',
    rolldownOptions: {
      output: {
        manualChunks(id: string) {
          if (id.includes('node_modules/@mkkellogg/gaussian-splats-3d')) return 'splat-viewer';
          if (id.includes('node_modules/three')) return 'three';
          return undefined;
        },
      },
    },
  },
});
