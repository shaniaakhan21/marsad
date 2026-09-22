"use client";

import { useCallback, useEffect, useState } from "react";
import { api, connectors } from "@/lib/api";
import type { Correlation, IncidentSubmission } from "@/lib/types";
import { ActionButton, PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";

/** Synthetic incidents — the same scenario as scripts/seed_demo.py. */
const SCENARIO = [
  {
    label: "Al Maha Bank",
    body: {
      narrative:
        "Finance staff received a credential-harvesting email impersonating the internal SSO portal.",
      analyst_notes: "Two users submitted credentials before the page was blocked.",
      indicators: [
        { type: "DOMAIN", value: "sso-almaha-verify[.]com" },
        { type: "IP", value: "185.220.101.44" },
        { type: "IBAN", value: "AE07 0331 2345 6789 0123 456" },
      ],
      techniques: ["T1566.002", "T1078", "T1114", "T1567"],
      severity: "HIGH",
    },
  },
  {
    label: "Gulf Securities",
    body: {
      narrative: "Client-services mailbox compromised; external forwarding rule created.",
      indicators: [
        { type: "DOMAIN", value: "gulfsec-clientlogin.net" },
        { type: "IP", value: "185.220.101.44" }, // same attacker infrastructure
      ],
      techniques: ["T1566.002", "T1078", "T1114", "T1565"],
      severity: "HIGH",
    },
  },
  {
    label: "Emirates Capital",
    body: {
      narrative: "Portfolio team targeted by a lookalike login page on unrelated infrastructure.",
      indicators: [
        { type: "DOMAIN", value: "emcap-portal-secure.io" },
        { type: "IP", value: "91.219.238.12" }, // rotated — exact match will miss
      ],
      techniques: ["T1566.002", "T1078", "T1114", "T1567"],
      severity: "MEDIUM",
    },
  },
];

export default function Home() {
  const [health, setHealth] = useState<Record<string, string>>({});
  const [payloads, setPayloads] = useState<IncidentSubmission[]>([]);
  const [corr, setCorr] = useState<Correlation[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const next: Record<string, string> = {};
    await Promise.all(
      connectors.map(async (b, i) => {
        try {
          const h = await api.connectorHealth(b);
          next[SCENARIO[i].label] = `${h.local_incidents} local incident(s)`;
        } catch {
          next[SCENARIO[i].label] = "unreachable";
        }
      }),
    );
    setHealth(next);
    try { setCorr(await api.correlations()); } catch { /* core down */ }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  async function run() {
    setBusy(true); setErr(null); setPayloads([]);
    try {
      for (let i = 0; i < SCENARIO.length; i++) {
        const base = connectors[i];
        const { incident_id } = await api.createIncident(base, SCENARIO[i].body);
        // Inspect what will cross the boundary BEFORE sending it.
        const preview = await api.preview(base, incident_id);
        setPayloads((p) => [...p, preview]);
        await api.submit(base, incident_id);
        await refresh();
        await new Promise((r) => setTimeout(r, 600));
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const INDICATOR_LABEL: Record<string, string> = {
    IP: "a shared computer address",
    DOMAIN: "a shared web address",
    URL: "a shared web link",
    FILE_HASH: "the same attack file",
    ACCOUNT: "the same account",
    IBAN: "the same bank account",
    WALLET: "the same crypto wallet",
  };

  return (
    <main>
      <PageHeader
        eyebrow="01 · Operations"
        title="Three firms get attacked."
        lede={
          <>
            <p>Watch what each one shares, and what it keeps private.</p>
            <p className="mt-1.5">
              Two firms are hit by the same attacker. The third faces a similar trick, from
              different computers. Only a scrambled fingerprint of the attack leaves each firm —
              never the incident report itself.
            </p>
          </>
        }
        actions={
          <ActionButton onClick={run} disabled={busy}>
            {busy ? "Running…" : "▶ Run the demo"}
          </ActionButton>
        }
      />

      <div className="space-y-4 p-8">
        {err && (
          <p className="rounded-[14px] border border-ember/40 bg-ember/10 p-3 text-sm text-text-primary">
            {err} — this demo isn&apos;t running. Start it with <code className="font-mono">make run</code>.
          </p>
        )}

        <div className="grid gap-3.5 md:grid-cols-3">
          {SCENARIO.map((s, i) => (
            <Panel key={s.label} label={`Firm ${i + 1} of 3 — its own private files`}>
              <p className="font-display text-[18px] font-bold text-text-primary">{s.label}</p>
              <p className="mt-1 font-mono text-[13.5px] text-text-faint">{connectors[i]}</p>
              <p className="mt-2 font-mono text-[13.5px] text-volt">{health[s.label] ?? "…"}</p>
              <p className="mt-3 border-t border-line pt-2 text-[12.5px] leading-relaxed text-text-secondary">
                The incident report and any customer data never leave this firm.
              </p>
            </Panel>
          ))}
        </div>

        <div className="grid gap-3.5 lg:grid-cols-[1.15fr_0.85fr]">
          <Panel label="What actually left each firm">
            <pre className="max-h-96 overflow-auto rounded-[8px] bg-sunken p-3 font-mono text-[13px] leading-relaxed text-text-secondary">
{payloads.length === 0
  ? "// Run the demo to see exactly what was shared."
  : JSON.stringify(payloads, null, 2)}
            </pre>
          </Panel>

          <Panel label="Matches found — without seeing anyone's incident report">
            <div className="max-h-96 space-y-2 overflow-auto">
              {corr.length === 0 && (
                <p className="text-[13.5px] text-text-faint">No matches yet.</p>
              )}
              {corr.map((c, i) => (
                <div
                  key={i}
                  className={`rounded-[10px] border p-3 text-[13.5px] ${
                    c.kind === "EXACT_TOKEN"
                      ? "border-band-low/40 bg-band-low/10"
                      : "border-band-mid/40 bg-band-mid/10"
                  }`}
                >
                  <p className="mb-1 font-mono text-[12.5px] font-extrabold tracking-wide text-text-primary">
                    {c.kind === "EXACT_TOKEN"
                      ? "◆ SAME ATTACKER"
                      : "◆ SIMILAR ATTACK METHOD"}
                  </p>
                  <p className="text-text-secondary">
                    {c.institutions ?? (c.peer_count ?? 0) + 1} firms hit ·{" "}
                    {c.indicator_type ? INDICATOR_LABEL[c.indicator_type] ?? c.indicator_type : "no shared detail"}
                    {c.similarity != null && <> · {(c.similarity * 100).toFixed(0)}% alike</>}
                  </p>
                  {c.shared_techniques.length > 0 && (
                    <p className="mt-1 font-mono text-[12.5px] text-text-faint">
                      {c.shared_techniques.join(", ")}
                    </p>
                  )}
                  <p className="mt-1 text-[12.5px] text-text-faint">
                    Safe to publish as a group total: {c.publishable_as_aggregate ? "yes" : "not yet"}
                    {c.reduced_fidelity && " · found with our simpler, less exact method"}
                  </p>
                </div>
              ))}
            </div>
          </Panel>
        </div>

        <p className="border-t border-line pt-3 text-[12.5px] leading-relaxed text-text-faint">
          This demo uses made-up incidents. Right now, the scrambling we use is good enough
          for a demo but not for real institutional data — production needs a stronger method that even
          we couldn&apos;t reverse, with its key split across several parties so no one of them
          can use it alone. Right now, we compare attack methods with a simple, fast check; a
          production system would use a slower, more accurate and more private one.
        </p>
      </div>
    </main>
  );
}
