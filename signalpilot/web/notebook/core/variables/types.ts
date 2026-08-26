import type { components } from "@/packages/sp-api";
import type { CellId } from "../cells/ids";

export type VariableName = components["schemas"]["VariableName"];

export interface Variable {
  name: VariableName;
  declaredBy: CellId[];
  usedBy: CellId[];
  /**
   * String representation of the value.
   */
  value?: string | null;
  /**
   * Type of the value.
   */
  dataType?: string | null;
}

export type Variables = Record<VariableName, Variable>;
