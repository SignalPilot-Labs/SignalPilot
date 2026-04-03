import AuthHeader, { type AuthUser } from "@/components/AuthHeader";

export default function AuthLayout({
  children,
  user,
}: {
  children: React.ReactNode;
  user?: AuthUser | null;
}) {
  return (
    <main className="min-h-screen flex flex-col items-center px-6 py-24">
      <div className="w-full max-w-[640px]">
        <AuthHeader user={user} />
        {children}
      </div>
    </main>
  );
}
