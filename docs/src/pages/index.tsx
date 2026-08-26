import type {ReactNode} from 'react';
import {Redirect} from '@docusaurus/router';
import useBaseUrl from '@docusaurus/useBaseUrl';
import Head from '@docusaurus/Head';

export default function Home(): ReactNode {
  const quickstart = useBaseUrl('/docs/');
  return (
    <>
      <Head>
        <meta httpEquiv="refresh" content={`0; url=${quickstart}`} />
      </Head>
      <Redirect to={quickstart} />
    </>
  );
}
