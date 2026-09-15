import {
  ACCENT,
  ACCENT_SOFT,
  AMBER,
  Arrow,
  Bar,
  BLUE,
  CheckDot,
  CrossDot,
  Cylinder,
  DIM,
  FILL,
  FILL_TINT,
  Frame,
  Label,
  MUTED,
  Node,
  RED,
  Shield,
  STROKE,
  STROKE_SOFT,
  TEXT,
  Window,
  Wire,
  type IllustrationProps,
} from './primitives';

/* Connect — app node → SignalPilot gateway (shielded) → warehouse cylinders. */
export function Connect(props: IllustrationProps) {
  return (
    <Frame width={320} height={200} {...props}>
      {/* app */}
      <Window x={14} y={62} w={86} h={62} />
      <Bar x={26} y={94} w={40} />
      <Bar x={26} y={104} w={56} />
      <circle cx={80} cy={96} r={6} fill={FILL_TINT} stroke={STROKE} strokeWidth={1.5} />
      <Label x={57} y={146} anchor="middle" upper>
        your AI app
      </Label>

      {/* wire */}
      <Wire d="M100 93 H124" />
      <Arrow x={126} y={93} />

      {/* gateway */}
      <rect x={122} y={54} width={94} height={78} rx={14} fill={ACCENT_SOFT} />
      <Node x={128} y={60} w={82} h={66} r={12} />
      <Shield x={158} y={70} s={22} />
      <Label x={169} y={112} anchor="middle" color={TEXT} size={10.5} weight={600}>
        SignalPilot
      </Label>
      <Label x={169} y={146} anchor="middle" upper>
        governed gateway
      </Label>

      {/* wire */}
      <Wire d="M216 93 H240" />
      <Arrow x={242} y={93} />

      {/* warehouses */}
      <Cylinder x={248} y={44} w={40} h={38} />
      <Cylinder x={266} y={78} w={40} h={38} accent />
      <Label x={277} y={146} anchor="middle" upper>
        warehouse
      </Label>

      {/* top annotation */}
      <Label x={169} y={30} anchor="middle" color={MUTED} size={9.5}>
        read-only SQL · audit log · knowledge
      </Label>
    </Frame>
  );
}

/* Governance — a SQL statement passes a filter: LIMIT added, DDL blocked, audit written. */
export function Governance(props: IllustrationProps) {
  return (
    <Frame width={320} height={200} {...props}>
      {/* incoming statements */}
      <Node x={12} y={40} w={104} h={30} r={8} />
      <Label x={22} y={59} color={TEXT} size={9.5}>
        SELECT … FROM orders
      </Label>
      <Node x={12} y={92} w={104} h={30} r={8} />
      <Label x={22} y={111} color={TEXT} size={9.5}>
        DROP TABLE orders
      </Label>
      <Label x={64} y={150} anchor="middle" upper>
        from the agent
      </Label>

      {/* filter gate */}
      <rect x={140} y={22} width={44} height={118} rx={12} fill={ACCENT_SOFT} />
      <Node x={146} y={28} w={32} h={106} r={10} />
      <line x1={162} y1={42} x2={162} y2={120} stroke={STROKE_SOFT} strokeWidth={1.5} strokeDasharray="2 4" />
      <Shield x={151} y={70} s={22} />
      <Label x={162} y={150} anchor="middle" upper>
        policy
      </Label>

      {/* wires in */}
      <Wire d="M116 55 H144" />
      <Wire d="M116 107 H144" />

      {/* outcomes */}
      <Wire d="M178 55 H204" />
      <Arrow x={206} y={55} />
      <Node x={208} y={40} w={100} h={30} r={8} />
      <CheckDot x={222} y={55} />
      <Label x={234} y={59} color={TEXT} size={9.5}>
        + LIMIT 1000
      </Label>

      <Wire d="M178 107 H204" />
      <Arrow x={206} y={107} />
      <Node x={208} y={92} w={100} h={30} r={8} />
      <CrossDot x={222} y={107} />
      <Label x={234} y={111} color={TEXT} size={9.5}>
        DDL blocked
      </Label>

      {/* audit ledger */}
      <Wire d="M162 134 V158" />
      <Arrow x={162} y={160} dir="down" />
      <Node x={110} y={162} w={104} h={30} r={8} fill={FILL_TINT} />
      <Bar x={120} y={172} w={30} color={STROKE} />
      <Bar x={156} y={172} w={18} color={STROKE} />
      <Bar x={120} y={182} w={48} color={STROKE_SOFT} />
      <Bar x={174} y={182} w={30} color={STROKE_SOFT} />
      <Label x={228} y={181} color={DIM} size={9.5} upper>
        audit log
      </Label>
    </Frame>
  );
}

/* Knowledge — cards of definitions feeding an answer. */
export function Knowledge(props: IllustrationProps) {
  const cards: Array<[number, string, string]> = [
    [34, 'revenue', 'net of refunds, USD'],
    [84, 'active user', '≥1 session / 30d'],
    [134, 'fiscal year', 'starts 1 Feb'],
  ];
  return (
    <Frame width={320} height={200} {...props}>
      {cards.map(([y, k, v]) => (
        <g key={k}>
          <Node x={14} y={y} w={122} h={38} r={9} />
          <Label x={26} y={y + 16} color={ACCENT} size={9.5} weight={600}>
            {k}
          </Label>
          <Label x={26} y={y + 29} color={MUTED} size={9}>
            {v}
          </Label>
          <Wire d={`M136 ${y + 19} C 170 ${y + 19}, 170 100, 200 100`} />
        </g>
      ))}
      <Label x={75} y={24} anchor="middle" upper>
        knowledge base
      </Label>

      <Arrow x={202} y={100} />

      {/* answer */}
      <rect x={204} y={58} width={106} height={84} rx={14} fill={ACCENT_SOFT} />
      <Node x={210} y={64} w={94} h={72} r={12} />
      <Label x={222} y={82} color={TEXT} size={10} weight={600}>
        Q1 revenue
      </Label>
      <Label x={222} y={100} color={TEXT} size={13} weight={600}>
        $4.21M
      </Label>
      <CheckDot x={230} y={118} r={6} />
      <Label x={242} y={121} color={MUTED} size={9}>
        uses 3 definitions
      </Label>
      <Label x={257} y={162} anchor="middle" upper>
        grounded answer
      </Label>
    </Frame>
  );
}

/* Warehouse — stack of cylinders with a schema tree. */
export function Warehouse(props: IllustrationProps) {
  return (
    <Frame width={320} height={200} {...props}>
      <Cylinder x={30} y={26} w={64} h={44} />
      <Cylinder x={30} y={74} w={64} h={44} accent />
      <Cylinder x={30} y={122} w={64} h={44} />
      <Label x={62} y={188} anchor="middle" upper>
        any warehouse
      </Label>

      <Wire d="M94 96 H126" />
      <Arrow x={128} y={96} />

      {/* schema tree */}
      <Node x={134} y={22} w={172} h={150} r={12} />
      <Label x={148} y={44} color={TEXT} size={10} weight={600}>
        analytics
      </Label>
      <path d="M156 50 V150" stroke={STROKE_SOFT} strokeWidth={1.5} />

      <path d="M156 68 H170" stroke={STROKE_SOFT} strokeWidth={1.5} />
      <Label x={176} y={72} color={MUTED} size={9.5}>
        marts
      </Label>
      <path d="M184 76 V132" stroke={STROKE_SOFT} strokeWidth={1.5} />
      <path d="M184 92 H198" stroke={STROKE_SOFT} strokeWidth={1.5} />
      <Label x={204} y={96} color={ACCENT} size={9.5}>
        fct_orders
      </Label>
      <Label x={270} y={96} color={DIM} size={8.5}>
        1.2M rows
      </Label>
      <path d="M184 112 H198" stroke={STROKE_SOFT} strokeWidth={1.5} />
      <Label x={204} y={116} color={MUTED} size={9.5}>
        dim_customers
      </Label>
      <path d="M184 132 H198" stroke={STROKE_SOFT} strokeWidth={1.5} />
      <Label x={204} y={136} color={MUTED} size={9.5}>
        dim_products
      </Label>

      <path d="M156 152 H170" stroke={STROKE_SOFT} strokeWidth={1.5} />
      <Label x={176} y={156} color={MUTED} size={9.5}>
        staging
      </Label>
      <Label x={230} y={156} color={DIM} size={8.5}>
        14 tables
      </Label>
    </Frame>
  );
}

/* Chat — a question bubble, an answer with a small results table and chart. */
export function Chat(props: IllustrationProps) {
  const rows = [0, 1, 2];
  const bars = [18, 30, 24, 38, 46];
  return (
    <Frame width={320} height={200} {...props}>
      {/* question */}
      <Node x={110} y={14} w={196} h={34} r={12} fill={FILL_TINT} />
      <Label x={124} y={35} color={TEXT} size={10}>
        Which region grew fastest?
      </Label>
      <circle cx={294} cy={31} r={7} fill={FILL} stroke={STROKE} strokeWidth={1.5} />

      {/* answer */}
      <Node x={14} y={62} w={230} h={124} r={14} />
      <Shield x={24} y={72} s={18} />
      <Label x={48} y={86} color={TEXT} size={10} weight={600}>
        West, +18% QoQ
      </Label>
      <Label x={48} y={98} color={MUTED} size={8.5}>
        1 query · 0.4s · 1,000 rows
      </Label>

      {/* table */}
      <Node x={26} y={108} w={104} h={66} r={6} fill={FILL_TINT} stroke={STROKE_SOFT} />
      <Bar x={34} y={116} w={30} color={STROKE} h={3} />
      <Bar x={74} y={116} w={22} color={STROKE} h={3} />
      <Bar x={102} y={116} w={20} color={STROKE} h={3} />
      <line x1={26} y1={124} x2={130} y2={124} stroke={STROKE_SOFT} strokeWidth={1.2} />
      {rows.map((i) => (
        <g key={i}>
          <Bar x={34} y={132 + i * 13} w={30} color={STROKE_SOFT} h={3} />
          <Bar x={74} y={132 + i * 13} w={22} color={STROKE_SOFT} h={3} />
          <Bar x={102} y={132 + i * 13} w={i === 0 ? 20 : 14} color={i === 0 ? ACCENT : STROKE_SOFT} h={3} />
        </g>
      ))}

      {/* chart */}
      <Node x={142} y={108} w={90} h={66} r={6} fill={FILL_TINT} stroke={STROKE_SOFT} />
      {bars.map((h, i) => (
        <rect
          key={i}
          x={152 + i * 15}
          y={166 - h}
          width={9}
          height={h}
          rx={2}
          fill={i === bars.length - 1 ? ACCENT : STROKE}
        />
      ))}
      <line x1={150} y1={166} x2={226} y2={166} stroke={STROKE_SOFT} strokeWidth={1.2} />

      <Label x={280} y={124} anchor="middle" upper>
        governed
      </Label>
      <Label x={280} y={136} anchor="middle" upper>
        answer
      </Label>
      <Wire d="M244 130 H262" />
    </Frame>
  );
}
