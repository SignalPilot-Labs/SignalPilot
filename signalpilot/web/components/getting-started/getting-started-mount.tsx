"use client";

import dynamic from "next/dynamic";
import { useAppAuth } from "~/lib/auth-context";

const GettingStartedRoot = dynamic(
  () => import("./getting-started-root").then((module) => module.GettingStartedRoot),
  { ssr: false },
);

export function GettingStartedMount() {
  const { clerkEnabled, isAuthenticated } = useAppAuth();
  if (!clerkEnabled || !isAuthenticated) return null;
  return <GettingStartedRoot />;
}
