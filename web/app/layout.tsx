import type { Metadata } from "next";
import "./globals.css";

// Stage name is RIPPLE — decisions/0005. The repo, docs and node-id scheme stay
// CHOKEPOINT; only what a judge sees or hears changes. Logo: /ripple-logo.png
export const metadata: Metadata = {
  title: "RIPPLE — depot viewer",
  icons: { icon: "/ripple-logo.png" },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
