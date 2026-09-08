/* Sidebar nav definitions: grouped items with href, label, icon, and
   ctrl+<shortcut> binding. Mirrored by components/ui/keyboard-shortcuts.tsx. */

import type React from "react";
import {
  NavIconAccuracy,
  NavIconAudit,
  NavIconChats,
  NavIconDashboard,
  NavIconDatabase,
  NavIconEvals,
  NavIconIntegrations,
  NavIconKnowledge,
  NavIconLineage,
  NavIconProject,
  NavIconReports,
  NavIconSandbox,
  NavIconSchema,
  NavIconSettings,
} from "~/components/layout/nav-icons";

export type NavIconComponent = React.FC<{ active: boolean }>;

export type NavItem = { href: string; label: string; icon: NavIconComponent; shortcut: string };

/* Grouped IA (see UX.md): trust loop first, then the data plane, then
   workspace curation. Health merged into Connections — a sick database is a
   property of a connection, not a place. */
export const navGroups: { label: string | null; items: NavItem[] }[] = [
  {
    label: null,
    items: [{ href: "/dashboard", label: "Dashboard", icon: NavIconDashboard, shortcut: "1" }],
  },
  {
    label: "Activity",
    items: [
      { href: "/chats", label: "Chats", icon: NavIconChats, shortcut: "" },
      { href: "/dashboards", label: "Dashboards", icon: NavIconDashboard, shortcut: "" },
      { href: "/reports", label: "Reports", icon: NavIconReports, shortcut: "9" },
      { href: "/audit", label: "Audit", icon: NavIconAudit, shortcut: "7" },
    ],
  },
  {
    label: "Data",
    items: [
      { href: "/connections", label: "Connections", icon: NavIconDatabase, shortcut: "2" },
      { href: "/schema", label: "Schema", icon: NavIconSchema, shortcut: "4" },
      { href: "/lineage", label: "Lineage", icon: NavIconLineage, shortcut: "6" },
    ],
  },
  {
    label: "Workspace",
    items: [
      { href: "/projects", label: "Projects", icon: NavIconProject, shortcut: "5" },
      { href: "/notebooks", label: "Notebooks", icon: NavIconSandbox, shortcut: "" },
      { href: "/knowledge", label: "Knowledge Base", icon: NavIconKnowledge, shortcut: "8" },
      { href: "/evals", label: "Evals", icon: NavIconEvals, shortcut: "" },
      { href: "/evals/accuracy", label: "Accuracy", icon: NavIconAccuracy, shortcut: "" },
      { href: "/integrations", label: "Integrations", icon: NavIconIntegrations, shortcut: "3" },
    ],
  },
  {
    label: null,
    items: [{ href: "/settings", label: "Settings", icon: NavIconSettings, shortcut: "0" }],
  },
];

export const nav: NavItem[] = navGroups.flatMap((g) => g.items);
