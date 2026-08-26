import React from "react";
import type { RequestingTree } from "@/components/editor/file-tree/requesting-tree";

export const RequestingTreeContext = React.createContext<RequestingTree | null>(null);
export const GitChangedFilesContext = React.createContext<Set<string>>(new Set());
