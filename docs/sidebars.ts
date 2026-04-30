import type {SidebarsConfig} from '@docusaurus/plugin-content-docs';

const sidebars: SidebarsConfig = {
  docsSidebar: [
    'intro',
    'getting-started',
    {
      type: 'category',
      label: 'How It Works',
      items: ['how-it-works'],
    },
    {
      type: 'category',
      label: 'Reference',
      items: ['tools', 'architecture', 'security'],
    },
    {
      type: 'category',
      label: 'Guides',
      items: ['plugin', 'mcp-clients', 'connect-database'],
    },
  ],
};

export default sidebars;
