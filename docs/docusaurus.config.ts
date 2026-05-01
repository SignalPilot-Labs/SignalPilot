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
          customCss: './src/css/custom.css',
        },
      } satisfies Preset.Options,
    ],
  ],

  themeConfig: {
    colorMode: {
      defaultMode: 'dark',
      disableSwitch: false,
      respectPrefersColorScheme: false,
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
        width: 32,
        height: 32,
      },
      items: [
        {
          to: '/docs/plugin',
          position: 'left',
          label: 'Plugin',
        },
        {
          to: '/docs/reference/tools-overview',
          position: 'left',
          label: 'Tools',
        },
        {
          href: 'https://app.signalpilot.ai',
          label: 'Cloud',
          position: 'right',
        },
        {
          href: 'https://github.com/SignalPilot-Labs/signalpilot',
          label: 'GitHub',
          position: 'right',
        },
      ],
    },
    footer: {
      style: 'light',
      links: [
        {
          title: 'Docs',
          items: [
            {
              label: 'Quickstart',
              to: '/docs/',
            },
            {
              label: 'Concepts',
              to: '/docs/concepts',
            },
            {
              label: 'MCP Setup',
              to: '/docs/mcp/connect-claude-code',
            },
            {
              label: 'Tools Reference',
              to: '/docs/reference/tools-overview',
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
      darkTheme: prismThemes.dracula,
      additionalLanguages: ['bash', 'json', 'sql', 'yaml', 'python', 'toml', 'ini'],
    },
  } satisfies Preset.ThemeConfig,
};

export default config;
