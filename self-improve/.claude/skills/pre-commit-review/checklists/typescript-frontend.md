# TypeScript Frontend Review Checklist

Scope: When diff contains `.tsx`/`.ts` files in `signalpilot/web/` or `self-improve/monitor-web/`

---

## Client Directive

Both frontends are fully client-rendered Next.js apps. No SSR data fetching is used.

- New files using `useState`, `useEffect`, `EventSource`, or `localStorage` missing `"use client"` at line 1
  - Every interactive component and page MUST have the directive
  - Missing it causes cryptic hydration errors in production
- New server components (`page.tsx` without `"use client"`) that attempt to use browser APIs

## API Layer

`signalpilot/web` uses a centralized `request<T>()` wrapper in `lib/api.ts`. `monitor-web` uses standalone async functions.

- **signalpilot/web:** New API calls not going through `lib/api.ts:request<T>()` — bypasses auth header injection
- **signalpilot/web:** Missing `getApiKey()` call or hardcoded API keys
- **monitor-web:** New API functions not following the error handling convention:
  - Non-critical data: return fallback value on failure (e.g., `fetchRepos` returns `[]`)
  - Critical data: throw explicitly so the caller can handle it
  - Do NOT mix styles in the same file
- Raw `fetch()` without checking `res.ok` before parsing JSON
- API error messages shown to user without passing through `_parseError()` or equivalent (strips HTTP status prefixes)

## SSE (Server-Sent Events)

Both apps use `EventSource` with named event listeners.

- New `EventSource` connections not closed in `useEffect` cleanup — causes connection leaks on unmount
  - Correct pattern: `return () => es.close()` in the effect cleanup
- Using `onmessage` instead of `addEventListener(eventName, handler)` — breaks named event routing
- SSE reconnection logic missing — `EventSource` auto-reconnects but state must be reset on reconnect
- **monitor-web:** New event types not handled in `useSSE.ts` event dispatch

## Component Patterns

- New pages missing a matching skeleton component for loading state
  - Pattern: one skeleton per page type (`DashboardSkeleton`, `ConnectionsSkeleton`)
  - Do NOT use a generic spinner as page-level loading state
- `useEffect` with missing dependency array (runs on every render)
- `useEffect` with object/array dependencies that cause infinite re-renders (unstable references)
- Missing `key` prop on list-rendered elements
- Event listeners added in `useEffect` without cleanup (memory leaks)

## Type Safety

Types are defined as plain interfaces in `lib/types.ts`. No runtime validation.

- Using `any` type where a specific interface exists in `types.ts`
- Inline return-type annotations on `request<ComplexInlineType>()` calls — extract to `types.ts` if reused
- Nullable fields typed as `T` instead of `T | null` (the codebase convention is explicit `| null`)
- New string literal union types (e.g., status values) not matching the backend's enum values

## State Management

No global state library. All state is local `useState` or encapsulated in custom hooks.

- State that should be in a hook (`useRuns`, `useSSE`, `useControl`) placed directly in a component
- Polling intervals (`setInterval`) not cleared on unmount
- `useRuns` polling (8s default) — new polling hooks should use similar intervals, not aggressive polling
- **signalpilot/web only:** Toast notifications: use `toast(msg, "error")` from `useToast()` for async failures, not `alert()` or `console.error()` (monitor-web has no toast system — errors appear as synthetic feed events via `useControl`)
