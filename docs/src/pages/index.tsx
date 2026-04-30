import type {ReactNode} from 'react';
import {Redirect} from '@docusaurus/router';
import useBaseUrl from '@docusaurus/useBaseUrl';
import Layout from '@theme/Layout';

export default function Home(): ReactNode {
  const quickstart = useBaseUrl('/docs/');
  return (
    <Layout>
      <Redirect to={quickstart} />
    </Layout>
  );
}
