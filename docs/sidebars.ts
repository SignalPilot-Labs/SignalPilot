import type {SidebarsConfig} from '@docusaurus/plugin-content-docs';

const sidebars: SidebarsConfig = {
  docsSidebar: [
    'quickstart',
    'concepts',
    'system-overview',
    {
      type: 'category',
      label: 'Setup',
      collapsed: false,
      items: [
        'setup/install',
        'setup/cloud',
        'setup/configuration',
      ],
    },
    {
      type: 'category',
      label: 'Connect Your Stack',
      collapsed: false,
      items: [
        'connect-database',
        'mcp/connect-claude-code',
        'mcp/connect-other-clients',
        'mcp/multiple-mcps',
        'mcp/auth',
      ],
    },
    {
      type: 'category',
      label: 'Plugin',
      collapsed: false,
      items: [
        'plugin',
        'plugin/install',
        'plugin/skills-overview',
        'plugin/skills-reference',
        'plugin/verifier-agent',
      ],
    },
    {
      type: 'category',
      label: 'Workflows',
      collapsed: false,
      items: [
        'how-it-works',
        'workflows/dbt-build',
        'workflows/sql-exploration',
        'workflows/custom-workflow',
        'workflows/claude-md-recipes',
      ],
    },
    {
      type: 'category',
      label: 'Reference',
      collapsed: true,
      items: [
        'reference/tools-overview',
        'reference/tools-query',
        'reference/tools-schema',
        'reference/tools-dbt',
        'reference/tools-ops',
        'reference/governance',
        'reference/dialects',
        'architecture',
        'security',
      ],
    },
  ],
};

export default sidebars;
