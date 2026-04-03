import AuthHeader from "@/components/AuthHeader";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <main className="min-h-screen flex flex-col items-center px-6 py-24">
      <div className="w-full max-w-[640px]">
        <AuthHeader />
        {children}
      </div>
    </main>
  );
}
