import type {ComponentType} from 'react';
import type {IllustrationProps} from './primitives';
import {Chat, Connect, Governance, Knowledge, Warehouse} from './set-a';
import {ApiKey, Connectors, Dashboard, Evals, SelfHost} from './set-b';

export type {IllustrationProps} from './primitives';
export {Chat, Connect, Governance, Knowledge, Warehouse} from './set-a';
export {ApiKey, Connectors, Dashboard, Evals, SelfHost} from './set-b';

export const illustrations = {
  connect: Connect,
  governance: Governance,
  knowledge: Knowledge,
  warehouse: Warehouse,
  chat: Chat,
  connectors: Connectors,
  apiKey: ApiKey,
  selfHost: SelfHost,
  evals: Evals,
  dashboard: Dashboard,
} satisfies Record<string, ComponentType<IllustrationProps>>;

export type IllustrationName = keyof typeof illustrations;

/** Name-based entry point, handy from MDX: `<Illustration name="connect" />`. */
export default function Illustration({
  name,
  ...rest
}: IllustrationProps & {name: IllustrationName}) {
  const Cmp = illustrations[name];
  return <Cmp {...rest} />;
}
