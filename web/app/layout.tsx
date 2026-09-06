import type { Metadata } from "next";
import "./globals.css";

// Stage name is RIPPLE — decisions/0005. The repo, docs and node-id scheme stay
// CHOKEPOINT; only what a judge sees or hears changes. Logo: /ripple-logo.png
// No `icons` entry: App Router serves app/favicon.ico automatically and it wins over
// anything declared here. Declaring both gives you two competing <link rel="icon"> tags.
export const metadata: Metadata = {
  title: "RIPPLE — depot viewer",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
