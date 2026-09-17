import {
  ACCENT,
  ACCENT_SOFT,
  AMBER,
  Arrow,
  Bar,
  BLUE,
  CheckDot,
  CrossDot,
  DIM,
  FILL,
  FILL_TINT,
  Frame,
  Label,
  MUTED,
  Node,
  Shield,
  STROKE,
  STROKE_SOFT,
  TEXT,
  Window,
  Wire,
  type IllustrationProps,
} from './primitives';

/* Connectors — SignalPilot hub with external MCP server plugs attached. */
export function Connectors(props: IllustrationProps) {
  const plugs: Array<{x: number; y: number; name: string; side: 'l' | 'r'}> = [
    {x: 14, y: 36, name: 'Notion', side: 'l'},
    {x: 14, y: 130, name: 'GitHub', side: 'l'},
    {x: 236, y: 36, name: 'Slack', side: 'r'},
    {x: 236, y: 130, name: 'Linear', side: 'r'},
  ];
  return (
    <Frame width={320} height={200} {...props}>
      {/* hub */}
      <rect x={116} y={62} width={88} height={78} rx={14} fill={ACCENT_SOFT} />
      <Node x={122} y={68} w={76} h={66} r={12} />
      <Shield x={149} y={78} s={22} />
      <Label x={160} y={120} anchor="middle" color={TEXT} size={10} weight={600}>
        SignalPilot
      </Label>
      <Label x={160} y={184} anchor="middle" upper>
        one governed endpoint
      </Label>

      {plugs.map((p) => {
        const px = p.side === 'l' ? p.x + 70 : p.x;
        const hx = p.side === 'l' ? 122 : 198;
        const py = p.y + 17;
        return (
          <g key={p.name}>
            <Node x={p.x} y={p.y} w={70} h={34} r={9} />
            <Label x={p.x + 35} y={p.y + 14} anchor="middle" color={TEXT} size={9.5} weight={600}>
              {p.name}
            </Label>
            <Label x={p.x + 35} y={p.y + 26} anchor="middle" color={DIM} size={8}>
              mcp server
            </Label>
            {/* plug prongs */}
            <line
              x1={px}
              y1={py - 4}
              x2={p.side === 'l' ? px + 6 : px - 6}
              y2={py - 4}
              stroke={STROKE}
              strokeWidth={2}
            />
            <line
              x1={px}
              y1={py + 4}
              x2={p.side === 'l' ? px + 6 : px - 6}
              y2={py + 4}
              stroke={STROKE}
              strokeWidth={2}
            />
            <Wire d={`M${p.side === 'l' ? px + 6 : px - 6} ${py} C ${(px + hx) / 2} ${py}, ${(px + hx) / 2} 101, ${hx} 101`} />
          </g>
        );
      })}
      <Label x={160} y={24} anchor="middle" color={MUTED} size={9.5}>
        every call audited on the way through
      </Label>
    </Frame>
  );
}

/* ApiKey — a key token being placed into a header field. */
export function ApiKey(props: IllustrationProps) {
  return (
    <Frame width={320} height={200} {...props}>
      {/* key token */}
      <rect x={82} y={30} width={156} height={36} rx={18} fill={ACCENT_SOFT} />
      <Node x={88} y={36} w={144} h={24} r={12} />
      {/* key glyph */}
      <g transform="translate(100 40)">
        <circle cx={6} cy={8} r={4.5} fill={FILL} stroke={ACCENT} strokeWidth={1.6} />
        <path d="M10 8 H22 M18 8 V12 M22 8 V11" stroke={ACCENT} strokeWidth={1.6} />
      </g>
      <Label x={130} y={52} color={TEXT} size={10.5} weight={600}>
        sp_••••••••••••7f3a
      </Label>
      <Label x={160} y={22} anchor="middle" upper>
        api key
      </Label>

      <Wire d="M160 66 V96" />
      <Arrow x={160} y={98} dir="down" />

      {/* header field */}
      <Node x={24} y={102} w={272} h={70} r={12} />
      <Label x={40} y={122} color={DIM} size={8.5} upper>
        Authorization header
      </Label>
      <Node x={40} y={130} w={240} h={28} r={7} fill={FILL_TINT} stroke={STROKE_SOFT} />
      <Label x={52} y={148} color={MUTED} size={10}>
        Bearer
      </Label>
      <Node x={100} y={135} w={128} h={18} r={9} fill={FILL} stroke={ACCENT} />
      <Label x={110} y={147} color={TEXT} size={9.5} weight={600}>
        sp_••••••••••••7f3a
      </Label>
      <CheckDot x={262} y={144} r={6} />
      <Label x={160} y={190} anchor="middle" upper>
        one key per person · revoke anytime
      </Label>
    </Frame>
  );
}

/* SelfHost — a small server rack with container slots. */
export function SelfHost(props: IllustrationProps) {
  const slots: Array<[number, string, string]> = [
    [34, 'gateway', ':3300'],
    [80, 'web', ':3000'],
    [126, 'postgres', ':5432'],
  ];
  return (
    <Frame width={320} height={200} {...props}>
      <Node x={70} y={18} w={180} h={166} r={14} />
      {slots.map(([y, name, port]) => (
        <g key={name}>
          <Node x={84} y={y} w={152} h={36} r={8} fill={FILL_TINT} stroke={STROKE_SOFT} />
          {/* container glyph */}
          <rect x={96} y={y + 10} width={16} height={16} rx={3} fill={FILL} stroke={STROKE} strokeWidth={1.5} />
          <rect x={100} y={y + 6} width={16} height={16} rx={3} fill={FILL} stroke={STROKE} strokeWidth={1.5} />
          <Label x={128} y={y + 16} color={TEXT} size={10} weight={600}>
            {name}
          </Label>
          <Label x={128} y={y + 28} color={DIM} size={8.5}>
            {port}
          </Label>
          <circle cx={218} cy={y + 18} r={3.5} fill={ACCENT} />
        </g>
      ))}
      <Label x={160} y={176} anchor="middle" color={DIM} size={8.5}>
        docker compose up
      </Label>
      <Label x={40} y={104} anchor="middle" upper>
        your
      </Label>
      <Label x={40} y={116} anchor="middle" upper>
        vpc
      </Label>
      <Wire d="M58 92 H68" />
      <Label x={284} y={104} anchor="middle" upper>
        own
      </Label>
      <Label x={284} y={116} anchor="middle" upper>
        data
      </Label>
      <Wire d="M252 92 H262" />
    </Frame>
  );
}

/* Evals — a checklist graded against gold answers. */
export function Evals(props: IllustrationProps) {
  const rows: Array<[string, string, boolean]> = [
    ['q01', '$4.21M', true],
    ['q02', '1,204', true],
    ['q03', '38.5%', false],
    ['q04', 'West', true],
  ];
  return (
    <Frame width={320} height={200} {...props}>
      {/* gold */}
      <Node x={14} y={30} w={110} h={130} r={12} />
      <Label x={69} y={20} anchor="middle" upper>
        gold answers
      </Label>
      {rows.map(([q, a], i) => (
        <g key={q}>
          <Label x={26} y={54 + i * 26} color={DIM} size={9}>
            {q}
          </Label>
          <Label x={56} y={54 + i * 26} color={TEXT} size={9.5}>
            {a}
          </Label>
        </g>
      ))}

      <Wire d="M124 95 H150" />
      <Arrow x={152} y={95} />

      {/* results */}
      <rect x={156} y={24} width={150} height={142} rx={14} fill={ACCENT_SOFT} />
      <Node x={162} y={30} w={138} h={130} r={12} />
      <Label x={231} y={20} anchor="middle" upper>
        agent answers
      </Label>
      {rows.map(([q, a, ok], i) => (
        <g key={q}>
          <Label x={176} y={54 + i * 26} color={DIM} size={9}>
            {q}
          </Label>
          <Label x={206} y={54 + i * 26} color={TEXT} size={9.5}>
            {ok ? a : '41.0%'}
          </Label>
          {ok ? <CheckDot x={282} y={50 + i * 26} r={6} /> : <CrossDot x={282} y={50 + i * 26} r={6} color={AMBER} />}
        </g>
      ))}
      <Label x={160} y={188} anchor="middle" color={MUTED} size={10}>
        3 / 4 pass · scored on the exact number
      </Label>
    </Frame>
  );
}

/* Dashboard — a window with stat tiles, bars and a line. */
export function Dashboard(props: IllustrationProps) {
  const bars = [22, 34, 28, 46, 40, 58];
  return (
    <Frame width={320} height={200} {...props}>
      <Window x={24} y={18} w={272} h={164} />
      {/* tiles */}
      {[0, 1, 2].map((i) => (
        <g key={i}>
          <Node x={36 + i * 84} y={48} w={76} h={40} r={8} fill={FILL_TINT} stroke={STROKE_SOFT} />
          <Bar x={46 + i * 84} y={57} w={28} h={3} color={STROKE} />
          <Label x={46 + i * 84} y={80} color={i === 0 ? ACCENT : TEXT} size={12} weight={600}>
            {['$4.2M', '+18%', '1,204'][i]}
          </Label>
        </g>
      ))}
      {/* bar chart */}
      <Node x={36} y={100} w={130} h={70} r={8} fill={FILL_TINT} stroke={STROKE_SOFT} />
      {bars.map((h, i) => (
        <rect key={i} x={48 + i * 19} y={160 - h} width={11} height={h} rx={2} fill={i === bars.length - 1 ? ACCENT : STROKE} />
      ))}
      {/* line chart */}
      <Node x={178} y={100} w={106} h={70} r={8} fill={FILL_TINT} stroke={STROKE_SOFT} />
      <path d="M190 154 L208 140 L226 146 L244 126 L262 130 L274 112" stroke={BLUE} strokeWidth={1.8} fill="none" />
      <circle cx={274} cy={112} r={3} fill={FILL} stroke={BLUE} strokeWidth={1.6} />
      <line x1={188} y1={160} x2={276} y2={160} stroke={STROKE_SOFT} strokeWidth={1.2} />
      <Label x={160} y={196} anchor="middle" upper>
        published from a chat
      </Label>
    </Frame>
  );
}
