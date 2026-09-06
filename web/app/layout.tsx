import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "CHOKEPOINT — sourcing risk console",
  description:
    "Trace a drug product to the precursor it shares, and see what else fails with it.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
