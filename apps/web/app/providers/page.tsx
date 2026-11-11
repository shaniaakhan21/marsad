"use client";

import { useState } from "react";
import { api, connectors, vendorConnector } from "@/lib/api";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";

const FIRMS = ["Al Maha Bank", "Gulf Securities", "Emirates Capital"];
const PROVIDER = { name: "Demo KYC provider (fictional)", domain: "kyc-vendor.example", substitutability: "NO" };

type Alert = { provider: string; severity_band: string; ts_bucket: string };

/**
 * Shared providers. Each firm declares its suppliers; only a token of each supplier's
 * domain leaves the firm. A supplier that is hit declares it once and every firm that
 * relies on it is warned, under the name that firm itself gave it.
 */
export default function ProvidersPage() {
  const [step, setStep] = useState<string | null>(null);
  const [sent, setSent] = useState<string | null>(null);
  const [notified, setNotified] = useState<number | null>(null);
  const [alerts, setAlerts] = useState<Alert[][]>(FIRMS.map(() => []));
  const [error, setError] = useState<string | null>(null);

  const declare = async () => {
    setError(null);
    try {
      for (let i = 0; i < FIRMS.length; i++) {
        setStep(`${FIRMS[i]} declares its supplier`);
        await api.saveDependencies(connectors[i], [PROVIDER]);
        const preview = await api.previewDependencies(connectors[i]);
        setSent(JSON.stringify(preview, null, 2));
        await api.publishDependencies(connectors[i], "demo.analyst");
      }
      setStep("All three firms have declared");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const outage = async () => {
    setError(null);
    try {
      const reply = await api.declareProviderIncident(vendorConnector, "HIGH", "vendor.analyst");
      setNotified(reply.core_response.dependents_notified);
      const next = await Promise.all(connectors.map(async (base) => {
        await api.collectNotices(base);
        return api.providerAlerts(base);
      }));
      setAlerts(next);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const button = "rounded-[8px] bg-volt px-4 py-2 text-[14.5px] font-semibold text-ink";

  return (
    <main>
      <PageHeader
        eyebrow="Shared providers"
        title="A supplier is hit. Every firm that relies on it hears once."
        lede="Firms declare suppliers by a token of the supplier's domain. The supplier's name never leaves the firm, and the supplier only learns how many firms rely on it."
      />
      <div className="grid gap-5 p-8 lg:grid-cols-2">
        <Panel label="1. Firms declare their supplier">
          <button type="button" className={button} onClick={declare}>Declare for all three firms</button>
          {step && <p className="mt-3 text-[14.5px] text-text-secondary">{step}</p>}
          {sent && (
            <>
              <p className="mt-4 text-[14px] text-text-secondary">What left the last firm. No name, no domain:</p>
              <pre className="mt-2 max-h-56 overflow-auto rounded-[8px] border border-line p-3 font-mono text-[12.5px] text-text-secondary">{sent}</pre>
            </>
          )}
        </Panel>

        <Panel label="2. The supplier declares an incident">
          <button type="button" className={button} onClick={outage}>Supplier reports an outage</button>
          {notified !== null && (
            <p className="mt-3 text-[14.5px] text-text-secondary" data-testid="dependents-notified">
              The supplier was told {notified} firm{notified === 1 ? "" : "s"} rely on it, and not which.
            </p>
          )}
        </Panel>

        <Panel label="3. What each firm sees" className="lg:col-span-2">
          <div className="grid gap-3 lg:grid-cols-3">
            {FIRMS.map((firm, i) => (
              <div key={firm} data-testid={`provider-alerts-${i}`} className="rounded-[10px] border border-line p-3">
                <p className="font-mono text-[12.5px] font-extrabold tracking-wide text-text-primary">Firm {i + 1}</p>
                <p className="mt-1 text-[14px] text-text-secondary">
                  {alerts[i].length
                    ? `${alerts[i][0].provider} reported a ${alerts[i][0].severity_band} incident.`
                    : "No supplier alerts."}
                </p>
              </div>
            ))}
          </div>
        </Panel>

        {error && <p className="text-[14px] text-ember lg:col-span-2">{error}</p>}
      </div>
    </main>
  );
}
