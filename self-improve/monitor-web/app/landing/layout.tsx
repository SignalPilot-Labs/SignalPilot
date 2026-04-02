export default function LandingLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="!overflow-auto" style={{ height: "auto", overflow: "auto" }}>
      <style>{`
        html, body { height: auto !important; overflow: auto !important; }
      `}</style>
      {children}
    </div>
  );
}
