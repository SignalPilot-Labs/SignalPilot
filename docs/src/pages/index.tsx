import type {ReactNode} from 'react';
import Layout from '@theme/Layout';
import {ClientMark} from '@site/src/components/ClientMark';
import {PageHero} from '@site/src/components/PageHero';
import {PathCards, PathCard} from '@site/src/components/PathCards';
import {FeatureGrid, FeatureCard} from '@site/src/components/FeatureGrid';
import {LinkTiles, LinkTile} from '@site/src/components/LinkTiles';
import {
  Connect,
  Connectors,
  Evals,
  Governance,
  Knowledge,
  Warehouse,
  Chat,
} from '@site/src/components/illustrations';
import styles from './index.module.css';

/*
 * TODO(docs-overhaul): confirm these routes against the final sidebars.ts.
 * onBrokenLinks is temporarily 'warn' in docusaurus.config.ts so the build
 * passes while content is still landing. Routes this page links to:
 *
 *   /docs/                          quickstart
 *   /docs/product/chat              "See what you can ask"
 *   /docs/clients/claude            PathCard + Jump to
 *   /docs/clients/chatgpt           PathCard + Jump to
 *   /docs/clients/claude-code       PathCard + Jump to
 *   /docs/clients/other-tools       PathCard
 *   /docs/clients/api-keys          Jump to (was /docs/mcp/auth — that page was removed)
 *   /docs/product/knowledge-base    FeatureCard + Jump to
 *   /docs/reference/governance      FeatureCard "Governed queries" (no /docs/product/governance yet)
 *   /docs/connect-database          FeatureCard "Connect any warehouse"
 *   /docs/settings/connectors       FeatureCard + Jump to
 *   /docs/workflows/dbt-build       FeatureCard "Verified dbt builds"
 *   /docs/evals/overview            FeatureCard "Evals"
 *   /docs/self-host/install         Jump to
 */
const ROUTES = {
  quickstart: '/docs/',
  whatToAsk: '/docs/product/chat',
  claude: '/docs/clients/claude',
  chatgpt: '/docs/clients/chatgpt',
  claudeCode: '/docs/clients/claude-code',
  otherTools: '/docs/clients/other-tools',
  knowledgeBase: '/docs/product/knowledge-base',
  governance: '/docs/reference/governance',
  warehouses: '/docs/connect-database',
  connectors: '/docs/settings/connectors',
  dbt: '/docs/workflows/dbt-build',
  evals: '/docs/evals/overview',
  auth: '/docs/clients/api-keys',
  selfHost: '/docs/self-host/install',
};

function SectionHeading({eyebrow, title, lede}: {eyebrow: string; title: string; lede?: string}) {
  return (
    <header className={styles.sectionHead}>
      <p className={styles.eyebrow}>{eyebrow}</p>
      <h2 className={styles.sectionTitle}>{title}</h2>
      {lede ? <p className={styles.sectionLede}>{lede}</p> : null}
    </header>
  );
}

export default function Home(): ReactNode {
  return (
    <Layout
      title="Docs"
      description="Connect Claude, ChatGPT, Claude Code or Cursor to your warehouse with governance built in.">
      <main className={styles.page}>
        <div className={styles.container}>
          <PageHero
            eyebrow="SignalPilot Docs"
            title={
              <>
                Talk to your data from the AI you already use, <em>safely</em>.
              </>
            }
            lede="Connect your warehouse once, then ask questions from Claude, ChatGPT, Claude Code or Cursor. Every query is read-only, logged, and grounded in your team's definitions."
            illustration={<Connect title="An AI app connected to a warehouse through the SignalPilot gateway" />}
            actions={[
              {label: 'Connect your AI in 5 minutes', to: ROUTES.quickstart, primary: true},
              {label: 'See what you can ask', to: ROUTES.whatToAsk},
            ]}
          />

          <section className={styles.section} aria-labelledby="pick-heading">
            <SectionHeading
              eyebrow="Start here"
              title="Pick how you work"
              lede="Each guide is a short, illustrated walkthrough. No terminal needed unless you want one."
            />
            <PathCards columns={4}>
              <PathCard
                title="Claude"
                description="claude.ai on web and desktop"
                to={ROUTES.claude}
                icon={<ClientMark client="claude" />}
                badge="Most popular"
              />
              <PathCard
                title="ChatGPT"
                description="Connect through custom connectors"
                to={ROUTES.chatgpt}
                icon={<ClientMark client="chatgpt" />}
              />
              <PathCard
                title="Claude Code"
                description="For engineers working in the terminal"
                to={ROUTES.claudeCode}
                icon={<ClientMark client="claude-code" />}
              />
              <PathCard
                title="Cursor and others"
                description="Codex, Windsurf and any MCP client"
                to={ROUTES.otherTools}
                icon={<ClientMark client="mcp" />}
              />
            </PathCards>
          </section>

          <section className={styles.section} aria-labelledby="what-heading">
            <SectionHeading
              eyebrow="What SignalPilot does"
              title="Governance you can see, answers you can trust"
              lede="SignalPilot sits between your AI and your warehouse. It keeps queries safe, remembers what your numbers mean, and shows its work."
            />
            <FeatureGrid columns={3}>
              <FeatureCard
                title="Governed queries"
                description="Every statement is read-only, row-limited and logged before it reaches the warehouse. Nothing gets dropped, changed or leaked."
                to={ROUTES.governance}
                illustration={<Governance />}
              />
              <FeatureCard
                title="Knowledge base"
                description="Write down how your team defines revenue, active users or fiscal quarters. Answers use those definitions automatically."
                to={ROUTES.knowledgeBase}
                illustration={<Knowledge />}
              />
              <FeatureCard
                title="Connect any warehouse"
                description="Snowflake, BigQuery, Postgres, Redshift, Databricks and more. One connection, shared by everyone in your workspace."
                to={ROUTES.warehouses}
                illustration={<Warehouse />}
              />
              <FeatureCard
                title="Bring in other MCP servers"
                description="Plug Notion, GitHub or your own tools into the same governed endpoint so one login covers everything."
                to={ROUTES.connectors}
                illustration={<Connectors />}
              />
              <FeatureCard
                title="Verified dbt builds"
                description="Ask for a new model and get one that is built, tested and checked against the numbers it is supposed to match."
                to={ROUTES.dbt}
                illustration={<Chat />}
              />
              <FeatureCard
                title="Evals"
                description="Grade your AI against gold answers on your own data, so you know how much to trust it before rolling it out."
                to={ROUTES.evals}
                illustration={<Evals />}
              />
            </FeatureGrid>
          </section>

          <section className={styles.section} aria-labelledby="popular-heading">
            <SectionHeading eyebrow="Popular pages" title="Jump to" />
            <LinkTiles columns={2}>
              <LinkTile eyebrow="Start" title="Quickstart" description="From sign-up to first answer" to={ROUTES.quickstart} />
              <LinkTile eyebrow="Connect" title="Use SignalPilot from Claude" description="Add it as a connector on claude.ai" to={ROUTES.claude} />
              <LinkTile eyebrow="Connect" title="Use SignalPilot from ChatGPT" description="Custom connector setup" to={ROUTES.chatgpt} />
              <LinkTile eyebrow="Connect" title="Claude Code, Cursor and Codex" description="One command for terminal tools" to={ROUTES.claudeCode} />
              <LinkTile eyebrow="Product" title="Knowledge base" description="Teach it your definitions" to={ROUTES.knowledgeBase} />
              <LinkTile eyebrow="Security" title="API keys and sign-in" description="Create, scope, and revoke access" to={ROUTES.auth} />
              <LinkTile eyebrow="Extend" title="External MCP connectors" description="Notion, GitHub and more through one endpoint" to={ROUTES.connectors} />
              <LinkTile eyebrow="Self-host" title="Self-host" description="Run the whole stack with Docker Compose" to={ROUTES.selfHost} />
            </LinkTiles>
          </section>
        </div>
      </main>
    </Layout>
  );
}
