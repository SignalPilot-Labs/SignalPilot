import {themes as prismThemes} from 'prism-react-renderer';
import type {Config} from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';

const config: Config = {
  title: 'SignalPilot',
  tagline: 'Governed AI agents for your data stack',
  favicon: 'img/favicon.ico',

  future: {
    v4: true,
  },

  url: 'https://SignalPilot-Labs.github.io',
  baseUrl: '/SignalPilot/',

  organizationName: 'SignalPilot-Labs',
  projectName: 'SignalPilot',
  trailingSlash: false,

  onBrokenLinks: 'throw',
  onBrokenMarkdownLinks: 'warn',

  i18n: {
    defaultLocale: 'en',
    locales: ['en'],
  },

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
      respectPrefersColorScheme: true,
    },
    navbar: {
      title: 'SignalPilot',
      items: [
        {
          type: 'docSidebar',
          sidebarId: 'docsSidebar',
          position: 'left',
          label: 'Docs',
        },
        {
          href: 'https://app.signalpilot.ai',
          label: 'Cloud',
          position: 'left',
        },
        {
          href: 'https://github.com/SignalPilot-Labs/SignalPilot',
          label: 'GitHub',
          position: 'right',
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
              label: 'Getting Started',
              to: '/docs/getting-started',
            },
            {
              label: 'MCP Tools',
              to: '/docs/tools',
            },
          ],
        },
        {
          title: 'Community',
          items: [
            {
              label: 'GitHub Discussions',
              href: 'https://github.com/SignalPilot-Labs/SignalPilot/discussions',
            },
            {
              label: 'Issues',
              href: 'https://github.com/SignalPilot-Labs/SignalPilot/issues',
            },
          ],
        },
        {
          title: 'More',
          items: [
            {
              label: 'signalpilot.ai',
              href: 'https://www.signalpilot.ai',
            },
            {
              label: 'AutoFyn',
              href: 'https://github.com/SignalPilot-Labs/AutoFyn',
            },
          ],
        },
      ],
      copyright: `Copyright ${new Date().getFullYear()} SignalPilot Labs. Apache 2.0.`,
    },
    prism: {
      theme: prismThemes.github,
      darkTheme: prismThemes.dracula,
      additionalLanguages: ['bash', 'json', 'sql', 'yaml'],
    },
  } satisfies Preset.ThemeConfig,
};

export default config;
