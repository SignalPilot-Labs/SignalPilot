import type {ReactNode} from 'react';
import {Redirect} from '@docusaurus/router';
import useBaseUrl from '@docusaurus/useBaseUrl';
import Head from '@docusaurus/Head';

// The docs home lives inside the docs layout (docs/home.mdx, slug "/") so the
// left navigation is always present. This page only forwards to it.
export default function Home(): ReactNode {
  const home = useBaseUrl('/docs/');
  return (
    <>
      <Head>
        <meta httpEquiv="refresh" content={`0; url=${home}`} />
      </Head>
      <Redirect to={home} />
    </>
  );
}
