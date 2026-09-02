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
    <aside className="fixed inset-y-0 left-0 z-20 flex w-[250px] flex-col border-r border-line bg-rail">
      <Link href="/" className="flex items-center gap-2.5 border-b border-line px-5 py-5">
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-[6px] bg-volt font-display text-sm font-extrabold text-ink">
          M
        </span>
        <span className="min-w-0">
          <span className="block font-display text-[15px] font-extrabold leading-none tracking-[-0.02em] text-text-primary">
            MARSAD
          </span>
          <span className="mt-1 block font-mono text-[9px] font-semibold uppercase tracking-[0.13em] text-text-muted">
            Cyber Resilience Obs.
          </span>
        </span>
      </Link>

      <nav className="px-3 pt-4">
        <p className="mb-2 px-2 font-mono text-[10px] font-semibold uppercase tracking-[0.13em] text-text-faint">
          / Workspace
        </p>
        <ul className="space-y-0.5">
          {TABS.map((t) => {
            const active = path === t.href;
            return (
              <li key={t.href}>
                <Link
                  href={t.href}
                  title={t.hint}
                  className={`flex items-center gap-2.5 rounded-[8px] px-2.5 py-2 font-mono text-[12px] font-semibold transition-colors duration-150 ease-console ${
                    active
                      ? "bg-volt text-ink"
                      : "text-text-secondary hover:bg-panel hover:text-text-primary"
                  }`}
                >
                  <span className={active ? "text-ink/55" : "text-text-faint"}>{t.n}</span>
                  <span className="truncate">{t.label}</span>
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>

      <div className="px-3 pt-6">
        <p className="mb-2 px-2 font-mono text-[10px] font-semibold uppercase tracking-[0.13em] text-text-faint">
          / Participants
        </p>
        <ul className="space-y-0.5">
          {PARTICIPANTS.map((label, i) => (
            <li key={label} className="flex items-center justify-between gap-2 rounded-[8px] px-2.5 py-1.5">
              <span className="flex min-w-0 items-center gap-2 text-[12px] text-text-secondary">
                <span
                  className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                    counts[i] !== null ? "bg-band-low" : "bg-text-faint"
                  }`}
                />
                <span className="truncate">{label}</span>
              </span>
              <span className="shrink-0 font-mono text-[11px] text-text-faint">
                {counts[i] ?? "—"}
              </span>
            </li>
          ))}
        </ul>
      </div>

      <div className="mt-auto border-t border-line px-5 py-4">
        <p className="flex items-center gap-1.5 font-mono text-[10px] font-semibold uppercase tracking-[0.1em] text-text-muted">
          <span className="h-1.5 w-1.5 rounded-full bg-band-low" />
          Feeds live · {live}/3
        </p>
        <p className="mt-2 text-[10px] leading-tight text-text-faint">
          Challenge #9 · Securities and Commodities Authority
          <br />
          now UAE Capital Market Authority
        </p>
      </div>
    </aside>
  );
}
