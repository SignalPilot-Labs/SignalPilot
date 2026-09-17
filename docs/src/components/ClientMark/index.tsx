import clsx from 'clsx';
import styles from './ClientMark.module.css';

export type ClientId =
  | 'claude'
  | 'chatgpt'
  | 'claude-code'
  | 'cursor'
  | 'codex'
  | 'openai'
  | 'mcp'
  | 'signalpilot';

export type ClientMarkProps = {
  client: ClientId;
  /** Glyph size in px. Defaults to 24. */
  size?: number;
  /** Show the client name next to the glyph. */
  label?: boolean;
  className?: string;
};

export const CLIENT_LABEL: Record<ClientId, string> = {
  claude: 'Claude',
  chatgpt: 'ChatGPT',
  'claude-code': 'Claude Code',
  cursor: 'Cursor',
  codex: 'Codex',
  openai: 'OpenAI',
  mcp: 'MCP',
  signalpilot: 'SignalPilot',
};

/* Abstract, monochrome marks. Deliberately not the vendors' logos: each is a
   simple geometric cue that reads as "that kind of client" at 20-32px. */
function Glyph({client}: {client: ClientId}) {
  const stroke = {
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 1.7,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
  };
  switch (client) {
    case 'claude':
      // eight-spoke burst
      return (
        <g {...stroke}>
          {[0, 45, 90, 135, 180, 225, 270, 315].map((a) => (
            <line key={a} x1="12" y1="12" x2="12" y2="4" transform={`rotate(${a} 12 12)`} />
          ))}
          <circle cx="12" cy="12" r="2.2" fill="currentColor" stroke="none" />
        </g>
      );
    case 'chatgpt':
      // hexagonal ring with an inner knot
      return (
        <g {...stroke}>
          <path d="M12 2.8 L20 7.4 V16.6 L12 21.2 L4 16.6 V7.4 Z" />
          <path d="M12 7.6 L15.8 9.8 V14.2 L12 16.4 L8.2 14.2 V9.8 Z" />
        </g>
      );
    case 'claude-code':
      // terminal prompt in a rounded square
      return (
        <g {...stroke}>
          <rect x="3" y="4" width="18" height="16" rx="4" />
          <path d="M7.5 9 L10.5 12 L7.5 15" />
          <path d="M12.5 15 H16.5" />
        </g>
      );
    case 'cursor':
      // pointer arrow
      return (
        <g {...stroke}>
          <path d="M5.5 4 L19 11.5 L12.8 13.2 L10.4 19 Z" />
        </g>
      );
    case 'codex':
      // angle brackets in a circle
      return (
        <g {...stroke}>
          <circle cx="12" cy="12" r="9" />
          <path d="M9.5 9 L7 12 L9.5 15 M14.5 9 L17 12 L14.5 15" />
        </g>
      );
    case 'openai':
      // ring of six petals, drawn as arcs
      return (
        <g {...stroke}>
          <circle cx="12" cy="12" r="8.5" />
          <circle cx="12" cy="12" r="3.2" />
          {[0, 60, 120, 180, 240, 300].map((a) => (
            <line key={a} x1="12" y1="8.8" x2="12" y2="3.5" transform={`rotate(${a} 12 12)`} />
          ))}
        </g>
      );
    case 'mcp':
      // plug
      return (
        <g {...stroke}>
          <path d="M8 3.5 V8 M16 3.5 V8" />
          <path d="M5.5 8 H18.5 V11 A6.5 6.5 0 0 1 5.5 11 Z" />
          <path d="M12 17.5 V21" />
        </g>
      );
    default:
      // signalpilot: nested hexagon outline with a dot (echoes the logo)
      return (
        <g {...stroke}>
          <path d="M12 2.6 L20.2 7.3 V16.7 L12 21.4 L3.8 16.7 V7.3 Z" />
          <path d="M8 5.2 L16.6 5.2 L20 11.2" />
          <circle cx="15.2" cy="9.4" r="1.6" fill="currentColor" stroke="none" />
        </g>
      );
  }
}

export function ClientMark({client, size = 24, label, className}: ClientMarkProps) {
  const name = CLIENT_LABEL[client];
  return (
    <span className={clsx(styles.mark, label && styles.withLabel, className)}>
      <svg
        viewBox="0 0 24 24"
        width={size}
        height={size}
        role={label ? 'presentation' : 'img'}
        aria-label={label ? undefined : name}
        aria-hidden={label ? true : undefined}
        className={styles.svg}>
        <Glyph client={client} />
      </svg>
      {label ? <span className={styles.label}>{name}</span> : null}
    </span>
  );
}

export default ClientMark;
