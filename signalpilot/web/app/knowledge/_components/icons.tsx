/* Iconography for the Knowledge Base — backed by lucide-react (the app's icon library).
   KbIcon maps a semantic name to a lucide icon so call sites stay stable.

   Audit (semantic → lucide):
     search→Search · edit→Pencil · history→History · close→X · plus→Plus · refresh→RefreshCw
     check→Check · ban/slash→Ban · archive→Archive · eye→Eye · eyeOff→EyeOff
     linkOut→ArrowUpRight · backlink→CornerDownLeft · live→Activity · sortArrows→ArrowUpDown
     doc→FileText · folder→Folder · filter→Filter · cpu(agent)→Bot · user→User
   Category glyphs:
     understanding→BookOpen · conventions→Ruler · decisions→Lightbulb
     domain-rules→Scale · debugging→Bug · quirks→Zap
*/
import type { CSSProperties } from "react";
import {
  Search, Pencil, History, X, Plus, RefreshCw, Check, Ban, Archive, Eye, EyeOff,
  ArrowUpRight, CornerDownLeft, Activity, ArrowUpDown, FileText, Folder, Filter,
  Bot, User, BookOpen, Ruler, Lightbulb, Scale, Bug, Zap, AlertCircle, Clock,
  ArrowDownToLine, Compass, Wrench,
  type LucideIcon,
} from "lucide-react";

const MAP: Record<string, LucideIcon> = {
  search: Search, edit: Pencil, history: History, close: X, plus: Plus, refresh: RefreshCw,
  check: Check, ban: Ban, slash: Ban, archive: Archive, eye: Eye, eyeOff: EyeOff,
  linkOut: ArrowUpRight, backlink: CornerDownLeft, live: Activity, sortArrows: ArrowUpDown,
  doc: FileText, folder: Folder, filter: Filter, cpu: Bot, user: User,
  // category glyphs
  bookOpen: BookOpen, braces: Ruler, bulb: Lightbulb, scale: Scale, bug: Bug, sparkles: Zap,
  // status
  clock: Clock, hourglass: AlertCircle, pull: ArrowDownToLine,
  // category glyphs (new taxonomy)
  compass: Compass, wrench: Wrench,
};

export function KbIcon({
  name,
  size = 14,
  className,
  style,
}: {
  name: string;
  size?: number;
  className?: string;
  style?: CSSProperties;
}) {
  const Comp = MAP[name];
  if (!Comp) return null;
  return (
    <span className={`kb-ic${className ? ` ${className}` : ""}`} style={style}>
      <Comp size={size} strokeWidth={1.8} />
    </span>
  );
}
