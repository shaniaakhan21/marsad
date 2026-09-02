import type {
  CohortReport, ConcentrationReport, ConfirmResult, Correlation, DataRegistry,
  ExtractionDraft, FreshnessReport, IncidentSubmission, MarketBasis,
  ObligationResult, Roadmap, SupervisorReport,
} from "./types";

const CORE = process.env.NEXT_PUBLIC_CORE_URL ?? "http://localhost:8000";
const CONNECTORS = (process.env.NEXT_PUBLIC_CONNECTORS ??
  "http://localhost:8101,http://localhost:8102,http://localhost:8103").split(",");

export const connectors = CONNECTORS;

async function json<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, { cache: "no-store", ...init });
  if (!r.ok) throw new Error(`${r.status} ${url}`);
  return r.json() as Promise<T>;
}

export const api = {
  coreHealth: () => json<{ ok: boolean; submissions: number }>(`${CORE}/health`),
  correlations: () => json<Correlation[]>(`${CORE}/v1/correlations`),

  connectorHealth: (base: string) =>
    json<{ ok: boolean; institution: string; local_incidents: number }>(`${base}/health`),

  obligations: (base: string, id: string) =>
    json<ObligationResult>(`${base}/v1/incidents/${id}/obligations`, { method: "POST" }),

  supervise: (base: string, id: string) =>
    json<SupervisorReport>(`${base}/v1/incidents/${id}/supervise`, { method: "POST" }),

  createIncident: (base: string, body: unknown) =>
    json<{ incident_id: string; supervisor?: SupervisorReport }>(`${base}/v1/incidents`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    }),

  /** A2 — propose a structured incident from free text. Files nothing. */
  extract: (base: string, body: { narrative: string; analyst_notes?: string; raw_email?: string }) =>
    json<{ draft: ExtractionDraft; supervisor: SupervisorReport }>(`${base}/v1/intake/extract`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    }),

  /** The human gate. Only this turns a proposal into an incident. */
  confirmDraft: (
    base: string,
    draftId: string,
    body: {
      analyst: string;
      edits?: Record<string, unknown>;
      jurisdictions?: string[];
      essential_service_affected?: boolean | null;
    },
  ) =>
    json<ConfirmResult>(`${base}/v1/intake/${draftId}/confirm`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    }),

  /** Inspect the outbound payload without sending it. */
  preview: (base: string, id: string) =>
    json<IncidentSubmission>(`${base}/v1/incidents/${id}/preview`, { method: "POST" }),

  submit: (base: string, id: string) =>
    json<{ submitted: boolean; core_response: { correlations: Correlation[] } }>(
      `${base}/v1/incidents/${id}/submit`, { method: "POST" }),

  // ---- evidence layer -----------------------------------------------------
  concentration: () => json<ConcentrationReport>(`${CORE}/v1/concentration`),
  dataSources: () => json<DataRegistry>(`${CORE}/v1/data/sources`),
  market: () => json<MarketBasis>(`${CORE}/v1/data/market`),
  cohorts: () => json<CohortReport>(`${CORE}/v1/data/cohorts`),
  roadmap: () => json<Roadmap>(`${CORE}/v1/roadmap`),
  freshness: () => json<FreshnessReport>(`${CORE}/v1/data/freshness`),
};
