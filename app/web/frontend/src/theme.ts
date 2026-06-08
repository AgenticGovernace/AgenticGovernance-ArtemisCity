/**
 * Artemis City — Glass Robo theme
 *
 * Ported from exo-homelab/index.html: dark navy gradient background,
 * glass panels (rgba(255,255,255,0.04) + backdrop-filter), and three
 * brand accent colors used for kernel/memory/attention semantics
 * (cyan / purple / amber). Mono typography for labels and tabular
 * values, display font for headlines.
 *
 * Exported as a Chakra v2 theme; wired into ChakraProvider in main.tsx.
 */

import { extendTheme, type ThemeConfig } from '@chakra-ui/react';

const config: ThemeConfig = {
  initialColorMode: 'dark',
  useSystemColorMode: false,
};

/** Brand palette (kernel-cyan, memory-purple, attention-amber). */
const accents = {
  kernel: '#22d3ee',
  kernelSoft: '#67e8f9',
  memory: '#a855f7',
  memorySoft: '#d8b4fe',
  attention: '#f59e0b',
  attentionSoft: '#fcd34d',
  ok: '#22c55e',
  okSoft: '#86efac',
  err: '#ef4444',
  errSoft: '#fca5a5',
};

const fg = {
  '0': '#f8fafc',
  '1': '#e2e8f0',
  '2': '#94a3b8',
  '3': '#64748b',
};

const bg = {
  page: '#050913',
  panel: 'rgba(255,255,255,0.04)',
  panelBorder: 'rgba(255,255,255,0.12)',
  inset: 'rgba(0,0,0,0.30)',
  sidebar: 'rgba(11,18,36,0.7)',
};

export const themeTokens = { accents, fg, bg };

const theme = extendTheme({
  config,
  fonts: {
    heading:
      "'Inter', system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
    body: "'Inter', system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
    mono: "'JetBrains Mono', 'SF Mono', 'Menlo', monospace",
  },
  colors: {
    brand: {
      50: '#ecfeff',
      100: '#cffafe',
      200: '#a5f3fc',
      300: '#67e8f9',
      400: '#22d3ee',
      500: '#06b6d4',
      600: '#0891b2',
      700: '#0e7490',
      800: '#155e75',
      900: '#164e63',
    },
    memory: {
      400: accents.memorySoft,
      500: accents.memory,
    },
    attention: {
      400: accents.attentionSoft,
      500: accents.attention,
    },
    fg,
    bg,
  },
  styles: {
    global: {
      'html, body': {
        background: `radial-gradient(ellipse at top, #0b1224 0%, #050913 100%) fixed`,
        color: fg['0'],
        minHeight: '100%',
      },
      body: {
        backgroundColor: bg.page,
      },
      '*::-webkit-scrollbar': {
        width: '8px',
        height: '8px',
      },
      '*::-webkit-scrollbar-thumb': {
        background: 'rgba(255,255,255,0.10)',
        borderRadius: '4px',
      },
      '*::-webkit-scrollbar-thumb:hover': {
        background: 'rgba(255,255,255,0.20)',
      },
    },
  },
  components: {
    Heading: {
      baseStyle: {
        color: fg['0'],
        letterSpacing: '-0.02em',
        fontWeight: 600,
      },
    },
    Text: {
      baseStyle: {
        color: fg['1'],
      },
    },
    Button: {
      baseStyle: {
        fontFamily: 'mono',
        fontWeight: 600,
        letterSpacing: '0.04em',
      },
      variants: {
        solid: {
          bg: 'rgba(34,211,238,0.12)',
          color: accents.kernelSoft,
          border: '1px solid',
          borderColor: 'rgba(34,211,238,0.30)',
          _hover: {
            bg: 'rgba(34,211,238,0.20)',
            boxShadow: `0 0 24px -6px ${accents.kernel}80`,
          },
        },
        outline: {
          bg: 'transparent',
          color: fg['1'],
          borderColor: bg.panelBorder,
          _hover: {
            bg: 'rgba(255,255,255,0.04)',
            color: fg['0'],
          },
        },
      },
    },
    Table: {
      variants: {
        simple: {
          th: {
            color: fg['3'],
            fontFamily: 'mono',
            fontSize: 'xs',
            letterSpacing: '0.12em',
            textTransform: 'uppercase',
            borderColor: bg.panelBorder,
          },
          td: {
            color: fg['1'],
            borderColor: 'rgba(255,255,255,0.06)',
            fontSize: 'sm',
          },
        },
      },
    },
    Modal: {
      baseStyle: {
        dialog: {
          bg: '#0b1224',
          color: fg['0'],
          borderRadius: '14px',
          border: '1px solid',
          borderColor: bg.panelBorder,
        },
      },
    },
    Drawer: {
      baseStyle: {
        dialog: {
          bg: bg.sidebar,
          color: fg['0'],
          backdropFilter: 'blur(18px)',
        },
      },
    },
    Alert: {
      baseStyle: {
        container: {
          borderRadius: '10px',
          border: '1px solid',
        },
      },
      variants: {
        subtle: ({ status }: { status: string }) => ({
          container: {
            bg:
              status === 'error'
                ? 'rgba(239,68,68,0.10)'
                : status === 'warning'
                ? 'rgba(245,158,11,0.10)'
                : status === 'success'
                ? 'rgba(34,197,94,0.10)'
                : 'rgba(34,211,238,0.10)',
            borderColor:
              status === 'error'
                ? 'rgba(239,68,68,0.30)'
                : status === 'warning'
                ? 'rgba(245,158,11,0.30)'
                : status === 'success'
                ? 'rgba(34,197,94,0.30)'
                : 'rgba(34,211,238,0.30)',
            color:
              status === 'error'
                ? accents.errSoft
                : status === 'warning'
                ? accents.attentionSoft
                : status === 'success'
                ? accents.okSoft
                : accents.kernelSoft,
          },
        }),
      },
    },
    Badge: {
      baseStyle: {
        fontFamily: 'mono',
        fontSize: 'xs',
        letterSpacing: '0.08em',
        textTransform: 'uppercase',
        borderRadius: '6px',
        fontWeight: 600,
      },
    },
    Input: {
      variants: {
        outline: {
          field: {
            bg: 'rgba(0,0,0,0.30)',
            borderColor: bg.panelBorder,
            color: fg['0'],
            fontFamily: 'mono',
            _placeholder: { color: fg['3'] },
            _hover: { borderColor: 'rgba(34,211,238,0.40)' },
            _focus: {
              borderColor: accents.kernel,
              boxShadow: `0 0 0 1px ${accents.kernel}`,
            },
          },
        },
      },
    },
    Textarea: {
      variants: {
        outline: {
          bg: 'rgba(0,0,0,0.30)',
          borderColor: bg.panelBorder,
          color: fg['0'],
          fontFamily: 'mono',
          _placeholder: { color: fg['3'] },
          _focus: {
            borderColor: accents.kernel,
            boxShadow: `0 0 0 1px ${accents.kernel}`,
          },
        },
      },
    },
    Select: {
      variants: {
        outline: {
          field: {
            bg: 'rgba(0,0,0,0.30)',
            borderColor: bg.panelBorder,
            color: fg['0'],
            fontFamily: 'mono',
            _focus: {
              borderColor: accents.kernel,
              boxShadow: `0 0 0 1px ${accents.kernel}`,
            },
          },
        },
      },
    },
  },
});

export default theme;
