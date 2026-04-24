"use client";

import { useEffect, type ReactNode } from "react";
import { useAuth, useUser, useOrganization, useOrganizationList } from "@clerk/nextjs";
import { AuthContext, type AppAuth, type AppUser } from "./auth-context";
import { setClerkTokenGetter } from "./api";

const IS_CLOUD_MODE = process.env.NEXT_PUBLIC_DEPLOYMENT_MODE === "cloud";

function OrgAwareProvider({ children, baseValue }: { children: ReactNode; baseValue: Omit<AppAuth, "activeOrgId" | "activeOrgName"> }) {
  const { organization } = useOrganization();
  const { userMemberships, setActive } = useOrganizationList({
    userMemberships: { infinite: true },
  });

  // Auto-activate first org if user is a member but no org is active on the session
  useEffect(() => {
    if (organization) return; // already active
    const memberships = userMemberships?.data ?? [];
    if (memberships.length > 0 && setActive) {
      const firstOrg = memberships[0].organization;
      setActive({ organization: firstOrg.id });
    }
  }, [organization, userMemberships?.data, setActive]);

  const value: AppAuth = {
    ...baseValue,
    activeOrgId: organization?.id ?? null,
    activeOrgName: organization?.name ?? null,
  } as AppAuth;
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function ClerkAuthInner({ children }: { children: ReactNode }) {
  const { isLoaded, isSignedIn, signOut, getToken } = useAuth();
  const { user: clerkUser } = useUser();

  // Wire Clerk's getToken into the gateway API client
  useEffect(() => {
    if (isLoaded && isSignedIn && getToken) {
      setClerkTokenGetter(getToken);
    }
  }, [isLoaded, isSignedIn, getToken]);

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

  const baseValue = {
    isAuthenticated: isSignedIn === true,
    isCloudMode: IS_CLOUD_MODE,
    isLocalMode: !IS_CLOUD_MODE,
    clerkEnabled: true,
    user,
    isLoaded,
    signOut: signOut ?? null,
  };

  console.log("[clerk-auth] isLoaded=", isLoaded, "isSignedIn=", isSignedIn, "user=", clerkUser?.id ?? null);

  // Only mount OrgAwareProvider (which calls useOrganization) when signed in
  if (isSignedIn) {
    return <OrgAwareProvider baseValue={baseValue}>{children}</OrgAwareProvider>;
  }

  const value: AppAuth = {
    ...baseValue,
    activeOrgId: null,
    activeOrgName: null,
  };
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
