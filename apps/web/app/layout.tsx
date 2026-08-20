import type { Metadata } from "next";
import { Nav } from "@/components/Nav";
import "./globals.css";

export const metadata: Metadata = {
  title: "MARSAD — Cyber Resilience Observatory",
  description:
    "UAE financial firms warn each other about cyberattacks, without sharing private details.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-ink font-sans text-text-primary antialiased">
        <Nav />
        <div className="min-w-[1120px] pl-[250px]">
          {children}
          <footer className="mx-auto max-w-5xl px-8 pb-10 pt-4 text-[10px] leading-relaxed text-text-faint">
            MARSAD · UAE Hackathon 2026 · Challenge #9, Securities and Commodities Authority
            (now the UAE Capital Market Authority) · Vertech Creations FZCO. The incidents in
            this demo are made up. The market and licensing numbers are real — see the
            Systemic exposure tab for where each one came from.
          </footer>
        </div>
      </body>
    </html>
  );
}
