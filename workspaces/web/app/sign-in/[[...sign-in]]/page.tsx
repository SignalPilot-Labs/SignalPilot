import { notFound } from "next/navigation";
import { SignIn } from "@clerk/nextjs";
import { getServerEnv } from "@/lib/env";

export default function SignInPage() {
  const env = getServerEnv();
  if (env.mode === "local") notFound();
  return (
    <main className="flex min-h-screen items-center justify-center">
      <SignIn />
    </main>
  );
}
