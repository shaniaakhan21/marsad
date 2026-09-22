"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { api, connectors } from "@/lib/api";

const TABS = [
  { href: "/demo", n: "00", label: "Guided demo", hint: "The whole thing, end to end, in ninety seconds" },
  { href: "/", n: "01", label: "Operations", hint: "Watch three firms warn each other, live" },
  { href: "/report", n: "02", label: "Report & guardrails", hint: "File a report and check every deadline" },
  { href: "/exposure", n: "03", label: "Systemic exposure", hint: "Which shared provider is riskiest, in AED" },
];

/** Same three firms as the Operations scenario — display only, read via the existing connector health endpoint. */
const PARTICIPANTS = ["Al Maha Bank", "Gulf Securities", "Emirates Capital"];

export function Nav() {
  const path = usePathname();
  const [counts, setCounts] = useState<(number | null)[]>([null, null, null]);

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      const next = await Promise.all(
        connectors.map(async (base) => {
          try {
            const h = await api.connectorHealth(base);
            return h.local_incidents;
          } catch {
            return null;
          }
        }),
      );
      if (!cancelled) setCounts(next);
    };
    void poll();
    const id = setInterval(poll, 4000);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  const live = counts.filter((c) => c !== null).length;

  return (
    <aside className="fixed inset-y-0 left-0 z-20 flex w-[250px] flex-col border-r border-rail-line bg-rail text-rail-text">
      <Link href="/" className="flex items-center gap-3 border-b border-rail-line px-5 py-5">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[8px] bg-rail-accent font-display text-[17px] font-bold text-rail">
          M
        </span>
        <span className="min-w-0">
          <span className="flex items-baseline gap-2 font-display text-[18px] font-bold leading-none tracking-[-0.01em] text-white">
            MARSAD
            <span className="font-arabic text-[15px] font-medium text-rail-muted" lang="ar">مرصد</span>
          </span>
          <span className="mt-1.5 block font-mono text-[11px] font-medium uppercase tracking-[0.08em] text-rail-muted">
            Cyber Resilience Obs.
          </span>
        </span>
      </Link>

      <nav className="px-3 pt-5">
        <p className="mb-2 px-2.5 font-mono text-[11px] font-semibold uppercase tracking-[0.12em] text-rail-faint">
          Workspace
        </p>
        <ul className="space-y-1">
          {TABS.map((t) => {
            const active = path === t.href;
            return (
              <li key={t.href}>
                <Link
                  href={t.href}
                  title={t.hint}
                  aria-current={active ? "page" : undefined}
                  className={`flex items-center gap-3 rounded-[8px] px-2.5 py-2.5 text-[14.5px] font-medium transition-colors duration-150 ease-console ${
                    active
                      ? "bg-rail-accent text-rail"
                      : "text-rail-text hover:bg-white/[0.07] hover:text-white"
                  }`}
                >
                  <span className={`font-mono text-[12px] ${active ? "text-rail/70" : "text-rail-faint"}`}>
                    {t.n}
                  </span>
                  <span className="truncate">{t.label}</span>
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>

      <div className="px-3 pt-7">
        <p className="mb-2 px-2.5 font-mono text-[11px] font-semibold uppercase tracking-[0.12em] text-rail-faint">
          Participants
        </p>
        <ul className="space-y-0.5">
          {PARTICIPANTS.map((label, i) => (
            <li key={label} className="flex items-center justify-between gap-2 rounded-[8px] px-2.5 py-2">
              <span className="flex min-w-0 items-center gap-2.5 text-[14px] text-rail-text">
                <span
                  className={`h-2 w-2 shrink-0 rounded-full ${
                    counts[i] !== null ? "bg-rail-accent" : "bg-rail-faint/60"
                  }`}
                />
                <span className="truncate">{label}</span>
              </span>
              <span className="shrink-0 font-mono text-[13px] text-rail-muted">
                {counts[i] ?? "—"}
              </span>
            </li>
          ))}
        </ul>
      </div>

      <div className="mt-auto border-t border-rail-line px-5 py-4">
        <p className="flex items-center gap-2 font-mono text-[11.5px] font-semibold uppercase tracking-[0.08em] text-rail-muted">
          <span className={`h-2 w-2 rounded-full ${live > 0 ? "bg-rail-accent" : "bg-rail-faint/60"}`} />
          Feeds live · {live}/3
        </p>
        <p className="mt-2 text-[12px] leading-snug text-rail-faint">
          Challenge #9 · Securities and Commodities Authority
          <br />
          now UAE Capital Market Authority
        </p>
      </div>
    </aside>
  );
}
