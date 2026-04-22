"use client";

import { createContext, useContext, type ReactNode } from "react";
import { useAuth, useUser } from "@clerk/nextjs";

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
}

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

const AuthContext = createContext<AppAuth | null>(null);

const IS_CLOUD_MODE = process.env.NEXT_PUBLIC_DEPLOYMENT_MODE === "cloud";

// ---------------------------------------------------------------------------
// Inner components — NEVER call Clerk hooks conditionally in a single body.
// ClerkAuthInner: always inside ClerkProvider, unconditionally calls hooks.
// LocalAuthInner: never inside ClerkProvider, returns static values.
// ---------------------------------------------------------------------------

function ClerkAuthInner({ children }: { children: ReactNode }) {
  const { isLoaded, isSignedIn, signOut } = useAuth();
  const { user: clerkUser } = useUser();

  const user: AppUser | null =
    isSignedIn && clerkUser
      ? {
          id: clerkUser.id,
          firstName: clerkUser.firstName,
          lastName: clerkUser.lastName,
          email: clerkUser.primaryEmailAddress?.emailAddress ?? null,
          imageUrl: clerkUser.imageUrl,
        }
      : null;

  const value: AppAuth = {
    isAuthenticated: isSignedIn === true,
    isCloudMode: IS_CLOUD_MODE,
    isLocalMode: !IS_CLOUD_MODE,
    clerkEnabled: true,
    user,
    isLoaded,
    signOut: signOut ?? null,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

function LocalAuthInner({ children }: { children: ReactNode }) {
  const value: AppAuth = {
    isAuthenticated: true, // local users have full access
    isCloudMode: IS_CLOUD_MODE,
    isLocalMode: !IS_CLOUD_MODE,
    clerkEnabled: false,
    user: null,
    isLoaded: true,
    signOut: null,
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
    return <ClerkAuthInner>{children}</ClerkAuthInner>;
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
