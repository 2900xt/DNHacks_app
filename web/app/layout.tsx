import type { Metadata } from "next";
import "./globals.css";

// Stage name is RIPPLE — decisions/0005. The repo, docs and node-id scheme stay
// CHOKEPOINT; only what a judge sees or hears changes. Logo: /ripple-logo.png
// `/` is the landing page and `/app` is the console, so the root title is the
// product's, not the instrument's. The console overrides both in
// app/app/page.tsx.
export const metadata: Metadata = {
  title: "RIPPLE — a supplier goes down. What else just broke?",
  description:
    "Detects disruption in public FDA feeds, propagates it through a real sourcing graph, and ranks the alternates that can actually supply you.",
};

// No `icons` entry here on purpose. In the App Router, app/favicon.ico is served
// automatically and beats anything declared in metadata.icons, so an entry here
// would either lose silently or ship two competing <link rel="icon"> tags —
// see brain team/LOG.md, Sat 22:20. Icons come from the file conventions:
// app/favicon.ico (16/32/48/64), app/icon.png and app/apple-icon.png.
//
// Those are built from the RIPPLE mark on a dark plate, because the mark is
// white-and-blue on transparent and its white strokes vanish against a light
// browser tab strip. The unmodified brand assets stay in public/ripple-logo.png
// (the full lockup) and public/ripple-logo.ico.
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
