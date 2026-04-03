"use client";

import { useSession } from "next-auth/react";
import AuthHeader from "@/components/AuthHeader";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  const { data: session } = useSession();
  const user = session?.user ?? null;

  return (
    <main className="min-h-screen flex flex-col items-center px-6 py-24">
      <div className="w-full max-w-[640px]">
        <AuthHeader user={user} />
        {children}
      </div>
    </main>
  );
}
