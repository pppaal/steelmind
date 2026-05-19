import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "steelmind — robot simulator",
  description: "Realtime humanoid telemetry and 3D visualization",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
