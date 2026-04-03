import type { Metadata, Viewport } from "next";
import { JetBrains_Mono } from "next/font/google";
import Providers from "@/components/Providers";
import "./globals.css";

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-jetbrains-mono",
  display: "swap",
});

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#000000",
};

export const metadata: Metadata = {
  title: "SignalPilot AutoCode",
  description: "AI-powered autonomous code improvement",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={jetbrainsMono.variable}>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
