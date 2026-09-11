import {themes as prismThemes} from 'prism-react-renderer';
import type {Config} from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';

const config: Config = {
  title: 'SignalPilot',
  tagline: 'Governed AI agents for your data stack',
  favicon: 'img/favicon.svg',

  future: {
    v4: true,
  },

  url: process.env.VERCEL_URL
    ? `https://${process.env.VERCEL_URL}`
    : 'https://SignalPilot-Labs.github.io',
  baseUrl: process.env.VERCEL ? '/' : '/SignalPilot/',

  organizationName: 'SignalPilot-Labs',
  projectName: 'SignalPilot',
  trailingSlash: false,

  onBrokenLinks: 'throw',
  markdown: {
    hooks: {
      onBrokenMarkdownLinks: 'warn',
    },
  },

  i18n: {
    defaultLocale: 'en',
    locales: ['en'],
  },

  headTags: [
    {
      tagName: 'link',
      attributes: {
        rel: 'apple-touch-icon',
        href: '/SignalPilot/img/apple-touch-icon.png',
      },
    },
    {
      tagName: 'meta',
      attributes: {
        property: 'og:image',
        content: '/SignalPilot/img/logo-512.png',
      },
    },
  ],

  plugins: [
    [
      '@docusaurus/plugin-client-redirects',
      {
        redirects: [
          {from: '/docs/mcp/auth', to: '/docs/clients/api-keys'},
          {from: '/docs/mcp/connect-claude-code', to: '/docs/clients/claude-code'},
          {from: '/docs/mcp/connect-other-clients', to: '/docs/clients/other-tools'},
          {from: '/docs/mcp/multiple-mcps', to: '/docs/clients/multiple-mcps'},
          {from: '/docs/setup/install', to: '/docs/self-host/install'},
          {from: '/docs/setup/configuration', to: '/docs/self-host/configuration'},
          {from: '/docs/setup/self-hosting-production', to: '/docs/self-host/production'},
          {from: '/docs/setup/operations', to: '/docs/self-host/operations'},
          {from: '/docs/setup/ssh-tunneling', to: '/docs/self-host/ssh-tunneling'},
          {from: '/docs/setup/cloud', to: '/docs/cloud'},
          {from: '/docs/setup/onboarding', to: '/docs/'},
        ],
      },
    ],
  ],

  presets: [
    [
      'classic',
      {
        docs: {
          sidebarPath: './sidebars.ts',
          editUrl:
            'https://github.com/SignalPilot-Labs/SignalPilot/tree/main/docs/',
        },
        blog: false,
        theme: {
          customCss: [
            // Order matters: these are the original custom.css split by concern,
            // listed in source order so the cascade is unchanged.
            './src/css/fonts-and-tokens.css',
            './src/css/base-typography.css',
            './src/css/chrome.css',
            './src/css/content.css',
            './src/css/page-furniture.css',
            './src/css/figures-and-utilities.css',
            './src/css/review-fixes.css',
          ],
        },
      } satisfies Preset.Options,
    ],
  ],

  themeConfig: {
    colorMode: {
      defaultMode: 'light',
      disableSwitch: false,
      respectPrefersColorScheme: true,
    },
    docs: {
      sidebar: {
        hideable: false,
      },
    },
    tableOfContents: {
      minHeadingLevel: 2,
      maxHeadingLevel: 4,
    },
    navbar: {
      title: 'SignalPilot',
      logo: {
        alt: 'SignalPilot',
        src: 'img/logo-light.svg',
        srcDark: 'img/logo.svg',
        width: 26,
        height: 26,
      },
      items: [
        {to: '/docs/', position: 'left', label: 'Docs'},
        {to: '/docs/clients/claude', position: 'left', label: 'Connect'},
        {to: '/docs/product/knowledge-base', position: 'left', label: 'Product'},
        {to: '/docs/self-host/install', position: 'left', label: 'Self-host'},
        {
          href: 'https://github.com/SignalPilot-Labs/signalpilot',
          label: 'GitHub',
          position: 'right',
        },
        // Last right-side link renders as the pill CTA (see src/css/chrome.css).
        // The theme toggle is injected after it by the theme, not by this list.
        {
          href: 'https://app.signalpilot.ai',
          label: 'Open SignalPilot',
          position: 'right',
          className: 'sp-nav-cta',
        },
      ],
    },
    footer: {
      style: 'dark',
      links: [
        {
          title: 'Docs',
          items: [
            {
              label: 'Quickstart',
              to: '/docs/',
            },
            {
              label: 'Connect Claude',
              to: '/docs/clients/claude',
            },
            {
              label: 'Knowledge base',
              to: '/docs/product/knowledge-base',
            },
            {
              label: 'Self-host',
              to: '/docs/self-host/install',
            },
          ],
        },
        {
          title: 'Product',
          items: [
            {
              label: 'Cloud',
              href: 'https://app.signalpilot.ai',
            },
            {
              label: 'Benchmarks',
              href: 'https://www.signalpilot.ai/benchmark',
            },
            {
              label: 'AutoFyn',
              href: 'https://github.com/SignalPilot-Labs/AutoFyn',
            },
          ],
        },
        {
          title: 'Community',
          items: [
            {
              label: 'GitHub Discussions',
              href: 'https://github.com/SignalPilot-Labs/signalpilot/discussions',
            },
            {
              label: 'Issues',
              href: 'https://github.com/SignalPilot-Labs/signalpilot/issues',
            },
            {
              label: 'Security',
              href: 'mailto:security@signalpilot.ai',
            },
          ],
        },
      ],
      copyright: `Copyright ${new Date().getFullYear()} SignalPilot Labs. Apache 2.0.`,
    },
    prism: {
      theme: prismThemes.github,
      darkTheme: prismThemes.vsDark,
      additionalLanguages: ['bash', 'json', 'sql', 'yaml', 'python', 'toml', 'ini'],
    },
  } satisfies Preset.ThemeConfig,
};

export default config;
