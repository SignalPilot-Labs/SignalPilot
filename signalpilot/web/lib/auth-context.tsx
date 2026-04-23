"use client";

import {
  createContext,
  useContext,
  lazy,
  Suspense,
  type ReactNode,
} from "react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface AppUser {
  id: string;
  firstName: string | null;
  lastName: string | null;
  email: string | null;
  imageUrl: string | null;
}

export interface AppAuth {
  /** true if Clerk says signed-in, OR if local mode without Clerk (full access) */
  isAuthenticated: boolean;
  /** NEXT_PUBLIC_DEPLOYMENT_MODE === "cloud" */
  isCloudMode: boolean;
  /** !isCloudMode */
  isLocalMode: boolean;
  /** Whether ClerkProvider is in the tree */
  clerkEnabled: boolean;
  /** null when not signed-in; never a fake user in local mode */
  user: AppUser | null;
  /** false while Clerk is initializing */
  isLoaded: boolean;
  /** null when Clerk is not loaded or in local mode */
  signOut: (() => Promise<void>) | null;
  /** Active Clerk organization ID; null in local mode or when no org is active */
  activeOrgId: string | null;
  /** Active Clerk organization display name; null in local mode or when no org is active */
  activeOrgName: string | null;
}

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

export const AuthContext = createContext<AppAuth | null>(null);

const IS_CLOUD_MODE = process.env.NEXT_PUBLIC_DEPLOYMENT_MODE === "cloud";

// ---------------------------------------------------------------------------
// Lazy-loaded Clerk inner component.
// This ensures @clerk/nextjs is NEVER imported when clerkEnabled=false.
// ---------------------------------------------------------------------------

const ClerkAuthInner = lazy(() =>
  import("./clerk-auth-inner").then((m) => ({ default: m.ClerkAuthInner }))
);

// ---------------------------------------------------------------------------
// Local-mode inner component (no Clerk dependency)
// ---------------------------------------------------------------------------

function LocalAuthInner({ children }: { children: ReactNode }) {
  const value: AppAuth = {
    isAuthenticated: true, // local users have full access
    isCloudMode: IS_CLOUD_MODE,
    isLocalMode: !IS_CLOUD_MODE,
    clerkEnabled: false,
    user: null,
    isLoaded: true,
    signOut: null,
    activeOrgId: null,
    activeOrgName: null,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// ---------------------------------------------------------------------------
// AuthProvider — selects inner component based on clerkEnabled prop.
// Does NOT call any hooks itself.
// ---------------------------------------------------------------------------

interface AuthProviderProps {
  clerkEnabled: boolean;
  children: ReactNode;
}

export function AuthProvider({ clerkEnabled, children }: AuthProviderProps) {
  if (clerkEnabled) {
    return (
      <Suspense fallback={null}>
        <ClerkAuthInner>{children}</ClerkAuthInner>
      </Suspense>
    );
  }
  return <LocalAuthInner>{children}</LocalAuthInner>;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useAppAuth(): AppAuth {
  const ctx = useContext(AuthContext);
  if (ctx === null) {
    throw new Error("useAppAuth must be called inside AuthProvider");
  }
  return ctx;
}
