/**
 * Mirrors packages/contracts/marsad_contracts/boundary.py
 *
 * Keep in sync by generating rather than editing by hand:
 *   python -m marsad_contracts.export_ts > apps/web/lib/types.ts
 *
 * The boundary contract exists in two languages, so drift here is a security
 * bug, not a typing inconvenience.
 */
export type IndicatorType =
  | "IP" | "DOMAIN" | "URL" | "FILE_HASH" | "ACCOUNT" | "IBAN" | "WALLET";
export type Sector = "BANK" | "BROKER" | "INVEST" | "EXCHANGE" | "INSURER" | "PROVIDER";
export type SizeBand = "SMALL" | "MID" | "LARGE";
export type SeverityBand = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
export type CorrelationKind = "EXACT_TOKEN" | "TECHNIQUE_SIMILARITY";

export interface KeyedToken { type: IndicatorType; token: string }

export interface IncidentSubmission {
  schema_version: "1.0";
  submission_id: string;
  institution_ref: string;
  tokens: KeyedToken[];
  technique_set: string[];
  coarse: {
    sector: Sector; size_band: SizeBand;
    severity_band: SeverityBand; ts_bucket: string;
  };
  obligation_ref?: { receipt_hash: string; authority: string; filed_at: string } | null;
  disclosure_rung: number;
}

export interface Correlation {
  kind: CorrelationKind;
  institutions?: number;
  peer_count?: number;
  indicator_type?: IndicatorType | null;
  shared_techniques: string[];
  similarity?: number | null;
  reduced_fidelity?: boolean;
  campaign_id?: string | null;
  detected_at?: string;
  publishable_as_aggregate?: boolean;
}

export interface ConcentrationScore {
  provider: string; score: number; band: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  dependents: number; market_activity_share: number; rationale: string;
}

/* ------------------------------------------------------------------ *
 * Evidence layer — mirrors marsad_core/data/uae_open_data.py and
 * marsad_core/data/roadmap.py. Same rule as above: generate, do not
 * hand-edit, once the exporter covers these.
 * ------------------------------------------------------------------ */

export type Verification = "VERIFIED" | "PAGE_VERIFIED" | "SYNDICATED" | "UNREACHABLE";

export interface DataSource {
  key: string;
  title: string;
  publisher: string;
  portal: string;
  url: string;
  access: string[];
  coverage: string;
  last_updated: string;
  verification: Verification;
  used_for: string;
  key_figures: Record<string, string>;
  caveat?: string | null;
}

export interface DataRegistry {
  sources: DataSource[];
  unreachable_portals: { portal: string; reason: string }[];
  counts: {
    total: number; verified: number; page_verified: number;
    syndicated: number; programmatic: number;
  };
  known_gap: string;
}

export interface MarketBasis {
  adx_market_cap_aed_bn: number;
  dfm_market_cap_aed_bn: number;
  listed_market_cap_aed_bn: number;
  avg_daily_traded_value_aed_bn: number;
  bank_assets_aed_bn: number;
  sources: string[];
  cross_check: {
    method: string;
    adx_fy2025_traded_aed_bn: number;
    dfm_fy2025_traded_aed_bn: number;
    trading_days_assumed: number;
    implied_daily_aed_bn: number;
    cma_reported_daily_aed_bn: number;
    agreement: string;
  };
}

export interface Exposure {
  market_activity_share: number;
  dependent_fraction: number;
  daily_traded_value_at_risk_aed_bn: number;
  weekly_traded_value_at_risk_aed_bn: number;
  listed_market_cap_in_scope_aed_bn: number;
  basis: string;
}

export interface ProviderRow extends ConcentrationScore {
  service: string;
  substitutability: "YES" | "PARTIAL" | "NO";
  inferred: boolean;
  exposure: Exposure;
}

export interface ConcentrationReport {
  total_participants: number;
  licensed_population: number;
  market_coverage: number;
  coverage_caveat: string;
  providers: ProviderRow[];
  basis: MarketBasis;
}

export interface CohortRule {
  sector: string;
  label: string;
  population: number;
  k_min: number;
  max_publishable_share: number;
  max_contributors_before_identifying: number;
  pooling_required: boolean;
  rationale: string;
}

export interface CohortReport {
  k_floor: number;
  max_cohort_share: number;
  universe: {
    cma_licensed_companies: number;
    cbuae_banks: number;
    addressable_first_wave: number;
    note: string;
    sources: string[];
  };
  cohorts: CohortRule[];
}

export interface Milestone {
  day: number; title: string; detail: string; owner: string; evidence: string;
}

export interface Phase {
  window: string;
  name: string;
  objective: string;
  why_this_order: string;
  exit_gate: string;
  success_metric: string;
  risk: string;
  mitigation: string;
  milestones: Milestone[];
}

/* ------------------------------------------------------------------ *
 * Live data provenance — mirrors marsad_core/data/fetchers.py and the
 * /v1/data/freshness route.
 * ------------------------------------------------------------------ */

export type FreshnessStatus = "LIVE" | "CACHED" | "PINNED";

export interface FreshnessEntry {
  source_key: string;
  status: FreshnessStatus;
  value: unknown;
  url: string;
  fetched_at: string;
  cache_age_days: number | null;
  detail: string | null;
}

export interface PopulationFreshnessEntry extends FreshnessEntry {
  sector: string;
  label: string;
}

export interface FreshnessReport {
  open_data: Record<string, FreshnessEntry>;
  population: Record<string, PopulationFreshnessEntry>;
  market: Record<string, FreshnessEntry>;
}

export interface Roadmap {
  horizon_days: number;
  sequencing_principle: string;
  phases: Phase[];
  resourcing: {
    team: string;
    critical_dependency: string;
    no_government_integration: string;
  };
  kill_criteria: string;
}


/* ------------------------------------------------------------------ *
 * A4 obligation resolver + A14 injection supervisor
 * ------------------------------------------------------------------ */

export type Applicability = "REQUIRED" | "REQUIRES_JUDGEMENT" | "NOT_APPLICABLE";

export interface Obligation {
  authority: string;
  label: string;
  applicability: Applicability;
  deadline: string | null;
  hours_allowed: number | null;
  hours_remaining: number | null;
  trigger: string;
  citation: string;
  reasoning: string;
  draft_notification: string;
  breached: boolean;
}

export interface ObligationResult {
  incident_severity: string;
  detected_at: string;
  corpus_version: string;
  notification_required: boolean;
  obligations: Obligation[];
  earliest_deadline: string | null;
  receipt_hash: string | null;
  judgement_calls: string[];
  note: string;
}

export type InjectionVerdict = "CLEAN" | "SUSPECTED" | "INJECTION";

export interface InjectionFinding {
  signature: string;
  why: string;
  weight: number;
  excerpt: string;
}

export interface SupervisorReport {
  verdict: InjectionVerdict;
  score: number;
  findings: InjectionFinding[];
  sanitised_length: number;
  original_length: number;
  analyst_message: string;
  logged_as_intelligence: boolean;
  extraction_blocked: boolean;
}


/* ------------------------------------------------------------------ *
 * A2 extraction — free-text intake. Mirrors
 * marsad_connector/agents/a2_extract.py. None of this crosses the
 * boundary: it is the local review surface an analyst confirms.
 * ------------------------------------------------------------------ */

export interface TrackedField {
  name: string;
  value: unknown;
  confidence: number;
  evidence: string | null;
  span: [number, number] | null;
  needs_attention: boolean;
  reason: string;
  edited: boolean;
  present: boolean;
  /** Values refused outright rather than flagged — see a2_extract._locatable_indicators. */
  rejected: unknown[];
}

export interface ExtractionDraft {
  draft_id: string;
  method: string;
  created_at: string;
  narrative: string;
  fields: Record<string, TrackedField>;
  needs_attention: string[];
  missing: string[];
  confidence_threshold: number;
  autonomy: "PROPOSE_CONFIRM";
  confirmed: false;
  narrative_normalised: string;
  language: "ENGLISH" | "ARABIC" | "MIXED";
  /** True when a language model proposed these fields rather than the cue tables. */
  model_proposed: boolean;
  /**
   * When true, confirm() refuses unless the analyst explicitly passes an indicators
   * edit. A model-proposed indicator becomes a token in a shared matching space that
   * nobody downstream can review, so it needs positive sign-off. See CLAUDE.md.
   */
  requires_indicator_confirmation: boolean;
}

export interface ConfirmResult {
  incident_id: string;
  confirmed_by: string;
  edited_fields: string[];
  severity: string;
  indicators: { type: string; value: string }[];
  techniques: string[];
  category: string | null;
  affected_services: string[];
  third_party_dependencies: string[];
}
