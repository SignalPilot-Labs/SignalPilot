"use client";

import { useState } from "react";

export default function NotebookTestPage() {
  const [loaded, setLoaded] = useState(false);

  return (
    <div className="h-screen w-full relative">
      {!loaded && (
        <div className="absolute inset-0 flex items-center justify-center text-gray-400 z-10">
          Loading notebook...
        </div>
      )}
      <iframe
        src="/marimo/index.html"
        onLoad={() => setLoaded(true)}
        className="w-full h-full border-0"
        style={{ opacity: loaded ? 1 : 0, transition: "opacity 150ms ease-in" }}
        allow="clipboard-read; clipboard-write"
      />
    </div>
  );
}
