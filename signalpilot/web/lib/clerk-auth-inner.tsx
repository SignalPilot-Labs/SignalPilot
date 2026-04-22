"use client";

import type { ReactNode } from "react";
import { useAuth, useUser } from "@clerk/nextjs";
import { AuthContext, type AppAuth, type AppUser } from "./auth-context";

const IS_CLOUD_MODE = process.env.NEXT_PUBLIC_DEPLOYMENT_MODE === "cloud";

export function ClerkAuthInner({ children }: { children: ReactNode }) {
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
