import type { Metadata } from "next";
import localFont from "next/font/local";
import "./globals.css";

// Self-hosted, never fetched: the venue network is assumed hostile. One face,
// IBM Plex Sans: an engineered grotesque that sits between a product-marketing
// sans and a terminal mono. Titles and readings use the same family, heavier,
// so nothing on screen reads as antique or as a shell.
const sans = localFont({
  variable: "--font-sans",
  display: "swap",
  src: [
    { path: "./fonts/IBMPlexSans-Regular.woff2", weight: "400", style: "normal" },
    { path: "./fonts/IBMPlexSans-Italic.woff2", weight: "400", style: "italic" },
    { path: "./fonts/IBMPlexSans-Medium.woff2", weight: "500", style: "normal" },
    { path: "./fonts/IBMPlexSans-SemiBold.woff2", weight: "600", style: "normal" },
    { path: "./fonts/IBMPlexSans-Bold.woff2", weight: "700", style: "normal" },
  ],
});

// Stage name is RIPPLE — decisions/0005. The repo, docs and node-id scheme stay
// CHOKEPOINT; only what a judge sees or hears changes. Logo: /ripple-logo.png
// `/` is the landing page and `/app` is the console, so the root title is the
// product's, not the instrument's. The console overrides both in
// app/app/page.tsx.
export const metadata: Metadata = {
  title: "RIPPLE Medicine",
  description:
    "We track where the world's drugs are actually made, notice when something goes wrong, and show you who else could make it instead.",
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
    <html lang="en" className={sans.variable}>
      <body>{children}</body>
    </html>
  );
}
