"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import type { ReceiptProof } from "@/lib/types";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";

const CHECKS: { key: keyof NonNullable<ReceiptProof["checks"]>; label: string }[] = [
  { key: "record_unchanged", label: "The stored record still matches what was anchored" },
  { key: "included_in_batch", label: "The receipt is part of the anchored batch" },
  { key: "root_on_ledger", label: "The batch's root is on the ledger" },
];

/** Anyone holding a receipt can check it. Hashes only: nothing about the firm or the incident. */
export default function VerifyPage() {
  const [receipt, setReceipt] = useState("");
  const [proof, setProof] = useState<ReceiptProof | null>(null);
  const [error, setError] = useState<string | null>(null);
  const valid = /^[0-9a-f]{64}$/.test(receipt.trim());

  const check = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setProof(null);
    try {
      setProof(await api.receiptProof(receipt.trim()));
    } catch (err) {
      const text = err instanceof Error ? err.message : String(err);
      setError(text.startsWith("404") ? "No report with this receipt is known." : text);
    }
  };

  return (
    <main>
      <PageHeader
        eyebrow="Audit ledger"
        title="Verify a receipt"
        lede="Paste a receipt to check that the report was anchored, when it was anchored, and that the record has not changed since."
      />
      <div className="space-y-5 p-8">
        <Panel label="Receipt">
          <form onSubmit={check} className="flex flex-wrap gap-3">
            <input
              aria-label="Receipt hash"
              value={receipt}
              onChange={(e) => setReceipt(e.target.value)}
              placeholder="64-character receipt hash"
              className="min-w-[280px] flex-1 rounded-[8px] border border-line bg-panel px-3 py-2 font-mono text-[14px] text-text-primary"
            />
            <button type="submit" disabled={!valid}
                    className="rounded-[8px] bg-volt px-4 py-2 text-[14.5px] font-semibold text-ink disabled:opacity-40">
              Verify
            </button>
          </form>
          {error && <p className="mt-3 text-[14px] text-ember">{error}</p>}
        </Panel>

        {proof && (
          <Panel label="Result" note={proof.status.replaceAll("_", " ")}>
            <p className={`text-[20px] font-semibold ${proof.verified ? "text-volt" : "text-ember"}`} data-testid="verdict">
              {proof.verified
                ? "Verified: this record is unchanged"
                : proof.status === "ANCHORED"
                  ? "Failed: this record does not match what was anchored"
                  : "Not anchored yet. Check again in a few minutes."}
            </p>
            {proof.checks && (
              <ul className="mt-4 space-y-2 text-[15px] text-text-secondary">
                {CHECKS.map((c) => (
                  <li key={c.key}>
                    <span className={proof.checks![c.key] ? "text-volt" : "text-ember"}>
                      {proof.checks![c.key] ? "Pass" : "Fail"}
                    </span>{" "}
                    {c.label}
                  </li>
                ))}
              </ul>
            )}
            {proof.ledger?.anchored_at && (
              <p className="mt-4 text-[14.5px] text-text-secondary">
                Anchored {new Date(proof.ledger.anchored_at).toLocaleString()} on {proof.ledger.backend}, block {proof.ledger.block}.
              </p>
            )}
            {proof.ledger?.reduced_fidelity && (
              <p className="mt-2 text-[14px] text-band-high">
                Test ledger: this hash chain sits in the operator&apos;s own database. An administrator could rewrite all of it, which the independent ledger prevents.
              </p>
            )}
          </Panel>
        )}
      </div>
    </main>
  );
}
