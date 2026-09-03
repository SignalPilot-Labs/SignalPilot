/**
 * Side-effect imports that register every card definition. `tool-card.tsx`
 * imports this module so the registry is populated before the first
 * resolve. Add each new card here (static import, no lazy loading).
 */
import "./generic-card";
import "./validation-card";
import "./dbt-run-card";
import "./terminal-card";
import "./knowledge-card";
import "./runtime-card";
import "./table-card";
import "./table-list-card";
import "./schema-card";
import "./column-profile-card";
