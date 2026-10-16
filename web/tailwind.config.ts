import type { Config } from 'tailwindcss';

export default {
  content: ['./src/**/*.{html,js,svelte,ts}'],
  darkMode: ['selector', '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        page: 'var(--bg-page)',
        card: 'var(--bg-card)',
        subtle: 'var(--bg-subtle)',
        hover: 'var(--bg-hover)',
        border: {
          main: 'var(--border-main)',
          strong: 'var(--border-strong)',
          subtle: 'var(--border-subtle)'
        },
        content: {
          primary: 'var(--text-primary)',
          secondary: 'var(--text-secondary)',
          muted: 'var(--text-muted)',
          caption: 'var(--text-caption)'
        },
        brand: {
          blue: 'var(--blue-primary)',
          'blue-hover': 'var(--blue-hover)',
          'blue-subtle': 'var(--blue-subtle)'
        },
        signal: {
          emerald: {
            bg: 'var(--emerald-bg)',
            text: 'var(--emerald-text)'
          },
          amber: {
            bg: 'var(--amber-bg)',
            text: 'var(--amber-text)',
            border: 'var(--amber-border)'
          },
          slate: {
            bg: 'var(--slate-tag-bg)',
            text: 'var(--slate-tag-text)'
          }
        }
      },
      fontFamily: {
        sans: [
          '-apple-system',
          'BlinkMacSystemFont',
          'Segoe UI',
          'Roboto',
          'Helvetica',
          'Arial',
          'sans-serif'
        ],
        mono: [
          'ui-monospace',
          'SFMono-Regular',
          'Menlo',
          'Monaco',
          'Consolas',
          'monospace'
        ]
      }
    }
  },
  plugins: []
} satisfies Config;
