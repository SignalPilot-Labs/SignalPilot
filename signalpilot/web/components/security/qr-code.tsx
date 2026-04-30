"use client";

import React, { useEffect, useRef } from "react";
import QRCode from "qrcode";

interface QrCodeProps {
  uri: string;
  size?: number;
}

export function QrCode({ uri, size = 192 }: QrCodeProps): React.JSX.Element {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    if (!canvasRef.current || !uri) return;
    QRCode.toCanvas(canvasRef.current, uri, {
      width: size,
      margin: 1,
      color: { dark: "#000000", light: "#ffffff" },
    }).catch((err: unknown) => {
      console.error("QR code generation failed", err);
    });
  }, [uri, size]);

  return (
    <div className="inline-block bg-white p-2 border border-[var(--color-border)]">
      <canvas ref={canvasRef} width={size} height={size} />
    </div>
  );
}
