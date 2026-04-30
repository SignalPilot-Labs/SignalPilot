import type {ReactNode} from 'react';
import clsx from 'clsx';
import Link from '@docusaurus/Link';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import Layout from '@theme/Layout';
import Heading from '@theme/Heading';

import styles from './index.module.css';

function HomepageHeader() {
  const {siteConfig} = useDocusaurusContext();
  return (
    <header className={clsx('hero hero--primary', styles.heroBanner)}>
      <div className="container">
        <Heading as="h1" className="hero__title">
          {siteConfig.title}
        </Heading>
        <p className="hero__subtitle">{siteConfig.tagline}</p>
        <div className={styles.buttons}>
          <Link
            className="button button--secondary button--lg"
            to="/docs/">
            Get Started
          </Link>
          <Link
            className="button button--outline button--lg"
            style={{marginLeft: '1rem', color: 'white', borderColor: 'white'}}
            href="https://app.signalpilot.ai">
            Try Cloud
          </Link>
        </div>
      </div>
    </header>
  );
}

type FeatureItem = {
  title: string;
  description: ReactNode;
  emoji: string;
};

const features: FeatureItem[] = [
  {
    title: 'SQL Governance',
    emoji: '🛡',
    description: (
      <>
        Every query is parsed, validated, and sandboxed. DDL/DML blocked,
        dangerous functions denied, LIMIT injected, PII redacted in audit logs.
      </>
    ),
  },
  {
    title: '32 MCP Tools',
    emoji: '🔧',
    description: (
      <>
        Schema exploration, query execution, dbt error parsing, join path
        finding, cost estimation, and more. All governed by default.
      </>
    ),
  },
  {
    title: '7 SQL Dialects',
    emoji: '🗄',
    description: (
      <>
        PostgreSQL, MySQL, SQLite, SQL Server, Snowflake, Databricks, and
        BigQuery. One MCP server, any warehouse.
      </>
    ),
  },
];

function Feature({title, emoji, description}: FeatureItem) {
  return (
    <div className={clsx('col col--4')}>
      <div className="text--center" style={{fontSize: '3rem'}}>
        {emoji}
      </div>
      <div className="text--center padding-horiz--md">
        <Heading as="h3">{title}</Heading>
        <p>{description}</p>
      </div>
    </div>
  );
}

export default function Home(): ReactNode {
  return (
    <Layout
      title="Governed AI agents for your data stack"
      description="SignalPilot is an open-source MCP server that gives AI agents safe, governed access to your databases.">
      <HomepageHeader />
      <main>
        <section style={{padding: '2rem 0'}}>
          <div className="container">
            <div className="row">
              {features.map((props, idx) => (
                <Feature key={idx} {...props} />
              ))}
            </div>
          </div>
        </section>
      </main>
    </Layout>
  );
}
