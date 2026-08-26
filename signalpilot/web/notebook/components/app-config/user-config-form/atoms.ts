import { atom } from "jotai";
import {
  CpuIcon,
  EditIcon,
  FlaskConicalIcon,
  FolderCog2,
  LayersIcon,
  MonitorIcon,
} from "lucide-react";

export const categories = [
  {
    id: "editor",
    label: "Editor",
    Icon: EditIcon,
    className: "bg-(--blue-4)",
  },
  {
    id: "display",
    label: "Display",
    Icon: MonitorIcon,
    className: "bg-(--grass-4)",
  },
  {
    id: "packageManagementAndData",
    label: "Packages & Data",
    Icon: LayersIcon,
    className: "bg-(--red-4)",
  },
  {
    id: "runtime",
    label: "Runtime",
    Icon: CpuIcon,
    className: "bg-(--amber-4)",
  },
  {
    id: "optionalDeps",
    label: "Optional Dependencies",
    Icon: FolderCog2,
    className: "bg-(--orange-4)",
  },
  {
    id: "labs",
    label: "Labs",
    Icon: FlaskConicalIcon,
    className: "bg-(--slate-4)",
  },
] as const;

export type SettingCategoryId = (typeof categories)[number]["id"];

export const activeUserConfigCategoryAtom = atom<SettingCategoryId>(
  categories[0].id,
);
