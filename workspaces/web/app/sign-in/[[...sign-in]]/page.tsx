import { notFound } from "next/navigation";
import { SignIn } from "@clerk/nextjs";
import { getServerEnv } from "@/lib/env";
import { AuthShell } from "@/components/auth/AuthShell";

export default function SignInPage() {
  const env = getServerEnv();
  if (env.mode === "local") notFound();
  return (
    <AuthShell title="$ workspaces sign-in" subtitle="sign in to continue">
      <SignIn />
    </AuthShell>
  );
}
