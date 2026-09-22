"use client";

import type { IncidentSubmission } from "@/lib/types";

/**
 * The boundary indicator. This component IS the product.
 *
 * Everything else on the dashboard is a consequence of one claim: narrative,
 * plaintext indicators and PII never leave the institution. A reviewer should not
 * have to take that on trust from prose — they should be able to look at two columns
 * and see, for this specific incident, exactly what stayed and exactly what left.
 *
 * The right-hand column is not a summary of the payload. It is derived from the
 * payload object itself, so it cannot drift from what was actually sent.
 *
 * Colour carries the meaning: petrol (`edge`) is the firm's own side, ochre (`core`)
 * is what crossed. Plaintext indicators stay red — sensitive, and local.
 */

export type LocalFacts = {
  narrative?: string | null;
  analystNotes?: string | null;
  rawEmail?: string | null;
  indicators?: { type: string; value: string }[];
  affectedServices?: string[];
  thirdParties?: string[];
  evidenceSpans?: number;
};

function Row({ label, value, dir }: { label: string; value: React.ReactNode; dir?: "rtl" | "ltr" }) {
  return (
    <div className="border-b border-line/80 py-2.5 first:pt-0 last:border-0 last:pb-0">
      <p className="font-mono text-[11px] font-medium uppercase tracking-[0.07em] text-text-faint">{label}</p>
      <p dir={dir} className="mt-1 break-words text-[14px] leading-relaxed text-text-secondary">
        {value}
      </p>
    </div>
  );
}

export function BoundaryIndicator({
  local,
  payload,
  rtl = false,
}: {
  local: LocalFacts;
  payload: IncidentSubmission | null;
  rtl?: boolean;
}) {
  const dir = rtl ? "rtl" : "ltr";

  return (
    <div className="grid gap-4 lg:grid-cols-2" data-testid="boundary-indicator">
      {/* ---------------------------------------------------------- stayed */}
      <section
        className="rounded-[14px] border border-edge/30 bg-edge/[0.045] p-5"
        data-testid="stayed-local"
      >
        <div className="mb-4 flex flex-wrap items-baseline justify-between gap-2 border-b border-edge/20 pb-3">
          <h3 className="font-mono text-[12.5px] font-bold uppercase tracking-[0.1em] text-edge">
            ◆ STAYED INSIDE THE FIRM
          </h3>
          <span className="font-mono text-[12px] text-text-faint">never transmitted</span>
        </div>

        {local.narrative && <Row label="Incident narrative" value={local.narrative} dir={dir} />}
        {local.analystNotes && <Row label="Analyst notes" value={local.analystNotes} dir={dir} />}
        {local.rawEmail && (
          <Row
            label="Attacker's email body"
            value={<span className="font-mono text-[12.5px]">{local.rawEmail.slice(0, 120)}…</span>}
          />
        )}
        {local.indicators && local.indicators.length > 0 && (
          <Row
            label={`Plaintext indicators (${local.indicators.length})`}
            value={
              <span className="font-mono text-[13px] font-medium text-ember">
                {local.indicators.map((i) => i.value).join(" · ")}
              </span>
            }
          />
        )}
        {local.affectedServices && local.affectedServices.length > 0 && (
          <Row label="Affected services" value={local.affectedServices.join(", ")} />
        )}
        {local.thirdParties && local.thirdParties.length > 0 && (
          <Row label="Named third parties" value={local.thirdParties.join(", ")} />
        )}
        {local.evidenceSpans != null && (
          <Row
            label="Extraction provenance"
            value={`${local.evidenceSpans} quoted spans — verbatim slices of the narrative`}
          />
        )}
      </section>

      {/* ---------------------------------------------------------- crossed */}
      <section
        className="rounded-[14px] border border-core/35 bg-core/[0.055] p-5"
        data-testid="crossed-boundary"
      >
        <div className="mb-4 flex flex-wrap items-baseline justify-between gap-2 border-b border-core/25 pb-3">
          <h3 className="font-mono text-[12.5px] font-bold uppercase tracking-[0.1em] text-core">
            ◆ CROSSED THE BOUNDARY
          </h3>
          <span className="font-mono text-[12px] text-text-faint">all of it, nothing else</span>
        </div>

        {!payload ? (
          <p className="text-[14px] text-text-faint">Nothing has been submitted yet.</p>
        ) : (
          <>
            <Row
              label={`Keyed tokens (${payload.tokens.length})`}
              value={
                <span className="font-mono text-[13px] font-medium text-core">
                  {payload.tokens.map((t) => `${t.type}:${t.token.slice(0, 12)}…`).join(" · ")}
                </span>
              }
            />
            <Row
              label="Attack techniques (public ATT&CK ids)"
              value={
                <span className="font-mono text-[13px] text-text-primary">
                  {payload.technique_set.join(", ") || "none"}
                </span>
              }
            />
            <Row
              label="Coarse metadata"
              value={`${payload.coarse.sector} · ${payload.coarse.size_band} · severity ${payload.coarse.severity_band}`}
            />
            <Row
              label="Detection time, bucketed to the hour"
              value={<span className="font-mono text-[13px] text-text-primary">{payload.coarse.ts_bucket}</span>}
            />
            <Row
              label="Institution reference"
              value={
                <span className="font-mono text-[13px] text-text-primary">
                  {payload.institution_ref}{" "}
                  <span className="font-sans text-text-faint">— a rotating pseudonym, not a name</span>
                </span>
              }
            />
          </>
        )}
      </section>
    </div>
  );
}

/**
 * The raw payload, unedited.
 *
 * The two columns above are our characterisation of what crossed. This is the object
 * itself, so a reviewer does not have to believe the characterisation — they can read
 * the bytes and search them.
 */
export function WhatTheCoreSees({ payload }: { payload: IncidentSubmission | null }) {
  return (
    <section className="rounded-[14px] border border-line bg-panel p-5 shadow-card" data-testid="core-sees">
      <div className="mb-4 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="font-mono text-[12px] font-semibold uppercase tracking-[0.1em] text-text-muted">
          What the core sees — the exact bytes that crossed
        </h3>
        <span className="font-mono text-[12px] text-text-faint">
          search it: no narrative, no plaintext indicator, no name
        </span>
      </div>
      <pre
        data-testid="core-sees-json"
        className="max-h-[300px] overflow-auto rounded-[10px] border border-line bg-sunken p-4 font-mono text-[12.5px] leading-relaxed text-text-primary"
      >
{payload ? JSON.stringify(payload, null, 2) : "// nothing submitted yet"}
      </pre>
      <p className="mt-3 border-t border-line pt-3 text-[13px] leading-relaxed text-text-faint">
        A token is a keyed, non-invertible reference. The core can compare two of them for
        equality and nothing else — it cannot recover the address, domain or account they came
        from. That is what makes a match possible without disclosure.
      </p>
    </section>
  );
}
