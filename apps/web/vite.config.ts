import { defineConfig, loadEnv, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';

/**
 * One codebase builds several apps; each app's public identity lives in .env.<app> and is selected with
 * `vite build --mode <app>` (npm run build:sailreels / build:sailtale / build:sailshort). With no app mode (dev, tests) the
 * SailReels values apply. index.html must carry the clientKey literally for TTMinis.init(), so it is
 * substituted here; a missing value fails the build instead of shipping a placeholder.
 */
const APP_DEFAULTS = { VITE_APP_NAME: 'SailReels', VITE_TIKTOK_CLIENT_KEY: 'mn_example_client_key' };

function appIdentity(env: Record<string, string>): Plugin {
  const values: Record<string, string> = { ...APP_DEFAULTS };
  for (const key in env) if (env[key]) values[key] = env[key];
  return {
    name: 'app-identity',
    transformIndexHtml(html) {
      return html.replace(/__(VITE_[A-Z_]+)__/g, (_, key: string) => {
        if (!values[key]) throw new Error(`index.html needs ${key}; set it in .env.<app>.`);
        return values[key];
      });
    },
  };
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', 'VITE_');  // '.' = apps/web, where npm scripts run
  return {
    plugins: [react(), appIdentity(env)],
    server: {
      host: true,
      port: 5177,
      strictPort: true,
      cors: {
        origin: true,
      },
      proxy: {
        '/api': 'http://localhost:18800',
      },
    },
    preview: {
      host: true,
      port: 4177,
      cors: true,
    },
    build: {
      target: ['es2020', 'safari13'],
    },
  };
});
