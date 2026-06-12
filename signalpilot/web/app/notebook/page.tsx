// Full-page notebook IDE. Same component as /projects, but the layout hides the
// left navbar and goes full-width for "/notebook" (see sidebar.tsx
// HIDDEN_SIDEBAR_PREFIXES and main-content.tsx FULL_WIDTH_PREFIXES). Used by the
// IDE header's "External" / pop-out link so it stays inside the authenticated
// app instead of hitting the gateway notebook URL directly (which lacks the
// proxy session cookie).
export { default } from "../projects/page";
