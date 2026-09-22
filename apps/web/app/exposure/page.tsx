"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { CohortReport, ConcentrationReport, FreshnessReport } from "@/lib/types";
import { PageHeader } from "@/components/PageHeader";
import { Band, Cell, FreshnessChip, Meter, Offline, Panel, Stat } from "@/components/Panel";

/**
 * Systemic exposure.
 *
 * The point of this view: don't show a score out of 100, show AED. Every
 * concentration score here is multiplied through real UAE market figures, and
 * the "out of how many firms" figure is the real licensed population, not
 * just the handful of firms in this demo.
 */
export default function ExposurePage() {
  const [rep, setRep] = useState<ConcentrationReport | null>(null);
  const [cohorts, setCohorts] = useState<CohortReport | null>(null);
  const [fresh, setFresh] = useState<FreshnessReport | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const [c, k] = await Promise.all([api.concentration(), api.cohorts()]);
        setRep(c);
        setCohorts(k);
      } catch (e) {
        setErr(e instanceof Error ? e.message : String(e));
      }
      // Freshness is best-effort: a slow or offline government portal must
      // never block the rest of the page from rendering.
      try { setFresh(await api.freshness()); } catch { /* chips just stay blank */ }
    })();
  }, []);

  if (err) return <main className="p-8"><Offline detail={err} /></main>;
  if (!rep || !cohorts) {
    return <main className="p-8 text-sm text-text-faint">Loading…</main>;
  }

  const b = rep.basis;
  const worst = rep.providers[0];
  const liveSourceLabel: Record<string, string> = {
    ajman_catalogue: "Open datasets published by Ajman government",
    ajman_business_licenses: "Active business licences in Ajman",
    tdra_mobile_subscriptions: "Active mobile phone subscriptions, UAE (Dec 2025)",
    bayanat_cbuae_series: "Central Bank balance-sheet series (federal open data portal)",
    dubai_pulse_pilot_volume: "Dubai Pulse pilot-volume series",
  };

  return (
    <main>
      <PageHeader
        eyebrow="03 · Systemic exposure"
        title="Which shared vendor would hurt the most firms at once — priced in AED, not a score."
        lede={
          <>
            <p>
              If a firm&apos;s vendor breaks, we turn that into real money at risk, using real UAE
              market numbers below. A regulator can act on &quot;AED 2.2 billion a day&quot; — not on
              &quot;risk score 87&quot;.
            </p>
            <p className="mt-2 rounded-[10px] border border-band-mid/40 bg-band-mid/10 p-2.5 text-[13px] leading-relaxed text-text-primary">
              <span className="font-semibold">How much of the market this covers: </span>
              {rep.coverage_caveat}
            </p>
          </>
        }
      />

      <div className="space-y-4 p-8">
        {/* ---------------- live UAE government data ---------------- */}
        <Panel
          label="Live UAE government data"
          note="checked right now, not typed in by hand"
        >
          <p className="mb-3 max-w-3xl text-[13.5px] leading-relaxed text-text-secondary">
            Most figures below are hand-verified numbers from PDF reports — government registers
            that have no public feed to connect to. These three are different: we call a real
            government website every time this page loads, live, right now.
          </p>
          <div className="grid gap-2.5 sm:grid-cols-3">
            {["ajman_catalogue", "ajman_business_licenses", "tdra_mobile_subscriptions"].map((key) => {
              const r = fresh?.open_data[key];
              return (
                <div key={key} className="rounded-[10px] border border-line bg-panel2 p-3">
                  <p className="text-[13px] text-text-faint">{liveSourceLabel[key] ?? key}</p>
                  <p className="mt-1 font-mono text-lg font-bold text-volt">
                    {r ? Number(r.value).toLocaleString() : "…"}
                  </p>
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <FreshnessChip freshness={r} />
                  </div>
                  {r && (
                    <a
                      href={r.url} target="_blank" rel="noreferrer"
                      className="mt-1.5 block truncate text-[11.5px] text-text-faint hover:text-volt hover:underline"
                    >
                      {r.url}
                    </a>
                  )}
                </div>
              );
            })}
          </div>
          <p className="mt-3 border-t border-line pt-2 text-[12.5px] leading-relaxed text-text-faint">
            If a portal doesn&apos;t answer within a few seconds, we show the last copy we saved
            instead, and say so. If we&apos;ve never reached it, we show a fixed number and say
            that too. We never make a number up.
          </p>
        </Panel>

        {/* ---------------- headline basis ---------------- */}
        <div className="grid gap-3.5 sm:grid-cols-2 lg:grid-cols-4">
          <Stat
            value={b.listed_market_cap_aed_bn.toLocaleString()}
            unit="AED bn"
            label="Total value of every company listed on a UAE stock market"
            source={`Abu Dhabi ${b.adx_market_cap_aed_bn.toLocaleString()} + Dubai ${b.dfm_market_cap_aed_bn.toLocaleString()} · CBUAE, Q4 2025`}
            chip={<FreshnessChip freshness={fresh?.market.adx_market_cap_aed_bn} />}
          />
          <Stat
            value={b.avg_daily_traded_value_aed_bn.toFixed(2)}
            unit="AED bn / day"
            label="Value traded on UAE markets in an average day"
            source="CMA, 2025 annual statement"
            tone="pink"
            chip={<FreshnessChip freshness={fresh?.market.avg_daily_traded_value_aed_bn} />}
          />
          <Stat
            value={b.bank_assets_aed_bn.toLocaleString()}
            unit="AED bn"
            label="Total assets held by UAE banks"
            source="CBUAE, Q4 2025"
            tone="violet"
            chip={<FreshnessChip freshness={fresh?.market.bank_assets_aed_bn} />}
          />
          <Stat
            value={worst.exposure.daily_traded_value_at_risk_aed_bn.toFixed(2)}
            unit="AED bn / day"
            label={`Trading value resting on our riskiest shared vendor (${worst.provider.split(" (")[0]})`}
            source="risk score × daily traded value"
            tone="plain"
          />
        </div>

        {/* ---------------- cross-check ---------------- */}
        <Panel
          label="Checking our own number against a second source"
          note={`the two agree, ${b.cross_check.agreement}`}
        >
          <p className="text-[13.5px] leading-relaxed text-text-secondary">
            Two different government reports both describe daily trading value. They should
            roughly match, so we check them against each other:{" "}
            <span className="font-mono text-volt">
              (Abu Dhabi {b.cross_check.adx_fy2025_traded_aed_bn} + Dubai{" "}
              {b.cross_check.dfm_fy2025_traded_aed_bn}) ÷{" "}
              {b.cross_check.trading_days_assumed} trading days ={" "}
              {b.cross_check.implied_daily_aed_bn} AED bn/day
            </span>{" "}
            against the CMA&apos;s own reported{" "}
            <span className="font-mono text-ember">
              {b.cross_check.cma_reported_daily_aed_bn} AED bn/day
            </span>
            . Two separate government sources, {b.cross_check.agreement}.
          </p>
        </Panel>

        {/* ---------------- provider ranking ---------------- */}
        <Panel
          label="Which shared vendor is riskiest"
          note="fixed formula · nothing here is guessed by AI"
        >
          <div className="space-y-2">
            {rep.providers.map((p) => {
              const open = expanded === p.provider;
              return (
                <div key={p.provider} className="rounded-[10px] border border-line bg-panel2 p-3">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <div>
                      <p className="text-[15.5px] font-semibold text-text-primary">
                        {p.provider}
                        {p.inferred && (
                          <span className="ml-2 rounded-full border border-band-mid/40 bg-band-mid/10 px-1.5 py-0.5 font-mono text-[11px] font-bold text-band-mid">
                            GUESSED LINK, NOT CONFIRMED
                          </span>
                        )}
                      </p>
                      <p className="text-[13px] text-text-faint">{p.service}</p>
                    </div>
                    <p className="font-mono text-lg font-bold text-text-primary">
                      {p.score.toFixed(1)}{" "}
                      <span className="text-[13.5px]">
                        <Band band={p.band} />
                      </span>
                    </p>
                  </div>

                  <div className="mt-2"><Meter pct={p.score} tone={p.band} /></div>

                  <div className="mt-3 grid gap-3 text-[13px] sm:grid-cols-3">
                    <Cell label="Money at risk per day" tone="ember" value={`AED ${p.exposure.daily_traded_value_at_risk_aed_bn.toFixed(2)} bn`} />
                    <Cell label="Market value that touches this vendor" tone="volt" value={`AED ${p.exposure.listed_market_cap_in_scope_aed_bn.toLocaleString()} bn`} />
                    <Cell
                      label="Could a firm switch away from it?"
                      tone="primary"
                      value={
                        p.substitutability === "NO" ? "No — no replacement exists"
                        : p.substitutability === "PARTIAL" ? "Only partly"
                        : "Yes — fairly easily"
                      }
                    />
                  </div>

                  <button
                    onClick={() => setExpanded(open ? null : p.provider)}
                    className="mt-2.5 flex w-full items-start gap-2 border-l-[3px] border-ember/60 pl-2.5 text-left"
                  >
                    <p className={`text-[12.5px] leading-relaxed text-text-secondary ${open ? "" : "line-clamp-1"}`}>
                      <span className="font-semibold text-text-primary">Why: </span>
                      {p.rationale}
                    </p>
                  </button>
                </div>
              );
            })}
          </div>
          <p className="mt-3 border-t border-line pt-2 text-[12.5px] leading-relaxed text-text-faint">
            These vendors are real — Aani, Jaywan and UAESWITCH are national payment rails named in
            CBUAE reports. Which firm depends on which vendor is our best guess for this demo: only
            the firms themselves can confirm that, and none has told us yet.
          </p>
        </Panel>

        {/* ---------------- k-anonymity calibration ---------------- */}
        <Panel
          label="Why we only publish group totals, never single-firm details"
          note={`never fewer than ${cohorts.k_floor} firms · never more than ${(cohorts.max_cohort_share * 100).toFixed(0)}% of a group`}
        >
          <p className="mb-3 max-w-3xl text-[13.5px] leading-relaxed text-text-secondary">
            We only publish a finding if the firms involved are a small slice of their peer group —
            otherwise, naming the group is almost the same as naming the firm. {cohorts.k_floor} of{" "}
            {cohorts.universe.cbuae_banks} licensed banks is a safe 4.9%: small enough that nobody
            can guess which {cohorts.k_floor}. The same {cohorts.k_floor} firms inside a 20-firm
            group would be 15% — too identifying, so we combine that group with a wider one before
            publishing anything about it. The group sizes come from the real CBUAE register, so
            this rule moves with the real market, not a number we picked.
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-[13px]">
              <thead className="text-text-faint">
                <tr className="border-b border-line">
                  <th className="py-1.5 pr-3 font-mono font-semibold uppercase tracking-wide">Group of firms</th>
                  <th className="py-1.5 pr-3 font-mono font-semibold uppercase tracking-wide">How many firms exist</th>
                  <th className="py-1.5 pr-3 font-mono font-semibold uppercase tracking-wide">Smallest group we&apos;d name</th>
                  <th className="py-1.5 pr-3 font-mono font-semibold uppercase tracking-wide">Most firms we can name at once</th>
                  <th className="py-1.5 pr-3 font-mono font-semibold uppercase tracking-wide">Can we publish this group?</th>
                  <th className="py-1.5 pr-3 font-mono font-semibold uppercase tracking-wide">Source</th>
                </tr>
              </thead>
              <tbody>
                {cohorts.cohorts.map((c) => (
                  <tr key={c.sector} className="border-b border-line/60 align-top">
                    <td className="py-1.5 pr-3 text-text-primary">{c.label}</td>
                    <td className="py-1.5 pr-3 font-mono text-text-secondary">{c.population}</td>
                    <td className="py-1.5 pr-3 font-mono text-text-secondary">{c.k_min}</td>
                    <td className="py-1.5 pr-3 font-mono">
                      {c.pooling_required ? (
                        <span
                          title="Even our smallest group would be too easy to identify inside this cohort"
                          className="text-text-faint"
                        >
                          none yet
                        </span>
                      ) : (
                        <span className="text-text-secondary">{c.max_contributors_before_identifying}</span>
                      )}
                    </td>
                    <td className="py-1.5 pr-3">
                      {c.pooling_required ? (
                        <span className="font-mono font-bold text-band-mid">MUST COMBINE WITH ANOTHER GROUP</span>
                      ) : (
                        <span className="font-mono font-bold text-band-low">YES</span>
                      )}
                    </td>
                    <td className="py-1.5 pr-3">
                      <FreshnessChip freshness={fresh?.population[c.sector]} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-3 text-[12.5px] leading-relaxed text-text-faint">
            {cohorts.universe.note}
          </p>
        </Panel>

        {/* Inline provenance. Not a citations page — just enough that every number on
            this screen names the government publication it came from. */}
        <p className="border-t border-line pt-3 text-[12.5px] leading-relaxed text-text-faint">
          <span className="font-semibold text-text-secondary">Where these numbers come from: </span>
          group sizes and the publishing rule, CBUAE <em>Annual Report 2025</em>, Table 4
          (checked monthly against the CBUAE <em>CB Register</em>) · market value and trading
          value, CBUAE <em>Q4 2025 Markets Report</em> · average daily trading value, the CMA&apos;s
          2025 statement · number of licensed firms, CMA <em>Licensed Companies</em> open data.
          The three figures above with a LIVE or CACHED tag are fetched from a government website
          directly by this app, right now — everything else is a hand-checked figure from a PDF or
          web page, refreshed by a person, not a machine.
        </p>
      </div>
    </main>
  );
}
