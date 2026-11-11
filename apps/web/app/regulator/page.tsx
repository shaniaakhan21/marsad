"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { RegulatorOverview } from "@/lib/types";
import { PageHeader } from "@/components/PageHeader";
import { Offline, Panel } from "@/components/Panel";

/** The market-wide view. Read-only, and every figure describes at least k firms. */
export default function RegulatorPage() {
  const [view, setView] = useState<RegulatorOverview | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.regulator().then(setView).catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  if (error) return <main className="p-8"><Offline detail={error} /></main>;
  if (!view) return <main className="p-8 text-sm text-text-faint">Loading…</main>;

  const row = "flex justify-between border-b border-line py-2 text-[15px] text-text-secondary last:border-0";
  const empty = <p className="text-[15px] text-text-faint">Nothing meets the publication threshold yet.</p>;

  return (
    <main>
      <PageHeader
        eyebrow="Regulator view"
        title="The market, with no firm in it"
        lede={`Read-only. A figure appears only when at least ${view.gate.k} separate firms stand behind it.`}
      />
      <div className="grid gap-5 p-8 lg:grid-cols-2">
        {!view.gate.satisfied && (
          <Panel label="Withheld" className="lg:col-span-2">
            <p className="text-[15px] text-text-secondary">
              Fewer than {view.gate.k} firms have reported, so nothing about them can be shown without identifying them.
            </p>
          </Panel>
        )}

        {view.campaigns && (
          <Panel label="Campaigns" note={`${view.campaigns.withheld_below_k} withheld below k`}>
            {view.campaigns.published.length === 0 ? empty : view.campaigns.published.map((c) => (
              <div key={c.campaign_id} className={row}>
                <span className="font-mono text-[14px]">{c.campaign_id.slice(0, 12)}</span>
                <span>{c.institutions} firms{c.reduced_fidelity ? " (reduced fidelity)" : ""}</span>
              </div>
            ))}
          </Panel>
        )}

        {view.sectors && (
          <Panel label="Sectors" note={view.sectors.pooling_applied ? "Small groups pooled" : undefined}>
            {view.sectors.groups.map((g) => (
              <div key={g.group} className={row}>
                <span>{g.group.replaceAll("_", " ")}</span>
                <span>{g.institutions} firms, {g.incidents} incidents</span>
              </div>
            ))}
          </Panel>
        )}

        {view.trend && (
          <Panel label="Weekly trend" note={`${view.trend.weeks_withheld_below_k} weeks withheld`}>
            {view.trend.weeks.length === 0 ? empty : view.trend.weeks.map((w) => (
              <div key={w.week} className={row}>
                <span className="font-mono text-[14px]">{w.week}</span>
                <span>{w.incidents} incidents</span>
              </div>
            ))}
          </Panel>
        )}

        {view.techniques && (
          <Panel label="Techniques in common">
            {view.techniques.length === 0 ? empty : view.techniques.slice(0, 8).map((t) => (
              <div key={t.technique} className={row}>
                <span className="font-mono text-[14px]">{t.technique}</span>
                <span>{t.institutions} firms</span>
              </div>
            ))}
          </Panel>
        )}

        <Panel label="Shared-provider risk" className="lg:col-span-2" note={view.concentration.coverage_caveat}>
          {view.concentration.providers.slice(0, 5).map((p) => (
            <div key={p.provider} className={row}>
              <span>{p.provider}</span>
              <span>{p.band}</span>
            </div>
          ))}
        </Panel>

        <Panel label="Financial impact" className="lg:col-span-2">
          <p className="text-[15px] text-text-secondary">{view.impact.reason}</p>
        </Panel>
      </div>
    </main>
  );
}
