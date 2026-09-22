export function Panel({
  label, children, className = "", note, flush = false,
}: {
  label: string; children: React.ReactNode; className?: string; note?: string;
  /** Edge-to-edge content (e.g. a table) — drops the card's own padding. */
  flush?: boolean;
}) {
  return (
    <section className={`rounded-[14px] border border-line bg-panel shadow-card ${flush ? "" : "p-5"} ${className}`}>
      <div className={`flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 ${flush ? "px-5 pt-5" : ""} mb-4`}>
        <h2 className="font-mono text-[12px] font-semibold uppercase tracking-[0.1em] text-text-muted">
          {label}
        </h2>
        {note && <span className="font-mono text-[12px] text-text-faint">{note}</span>}
      </div>
      {children}
    </section>
  );
}

const BAND_COLOR: Record<string, string> = {
  CRITICAL: "text-ember",
  HIGH: "text-band-high",
  MEDIUM: "text-band-mid",
  LOW: "text-band-low",
};

export function Band({ band }: { band: string }) {
  return <span className={`font-bold ${BAND_COLOR[band] ?? "text-text-secondary"}`}>{band}</span>;
}

/** A labelled data point with no box of its own — for grids of small figures. */
export function Cell({
  label, value, tone = "secondary",
}: {
  label: string; value: React.ReactNode;
  tone?: "primary" | "secondary" | "ember" | "volt";
}) {
  const toneCls = {
    primary: "text-text-primary",
    secondary: "text-text-secondary",
    ember: "text-ember",
    volt: "text-volt",
  }[tone];
  return (
    <div>
      <p className="font-mono text-[11.5px] uppercase tracking-[0.07em] text-text-faint">{label}</p>
      <p className={`mt-1 font-mono text-[15px] font-semibold ${toneCls}`}>{value}</p>
    </div>
  );
}

/** A single headline figure. Every one on this dashboard is traceable to a source. */
export function Stat({
  value, unit, label, source, tone = "cyan", chip,
}: {
  value: string; unit?: string; label: string; source?: string;
  tone?: "cyan" | "pink" | "violet" | "plain";
  chip?: React.ReactNode;
}) {
  const toneCls = {
    cyan: "text-volt",
    pink: "text-ember",
    violet: "text-text-primary",
    plain: "text-text-primary",
  }[tone];

  return (
    <div className="flex h-full flex-col rounded-[14px] border border-line bg-panel p-5 shadow-card">
      <p className={`font-mono text-[34px] font-semibold leading-none tracking-[-0.02em] ${toneCls}`}>
        {value}
        {unit && <span className="ml-2 text-[14px] font-normal tracking-normal text-text-muted">{unit}</span>}
      </p>
      <p className="mt-3 text-[14px] leading-snug text-text-secondary">{label}</p>
      <div className="mt-auto pt-3">
        {source && (
          <p className="border-t border-line pt-2.5 text-[12px] leading-snug text-text-faint">{source}</p>
        )}
        {chip && <p className="mt-2">{chip}</p>}
      </div>
    </div>
  );
}

/** Provenance badge. Deliberately shows weakness as well as strength. */
export function Verify({ status }: { status: string }) {
  const map: Record<string, string> = {
    VERIFIED: "border-band-low/40 bg-band-low/10 text-band-low",
    PAGE_VERIFIED: "border-line-strong bg-panel2 text-text-secondary",
    SYNDICATED: "border-band-mid/40 bg-band-mid/10 text-band-mid",
    UNREACHABLE: "border-ember/40 bg-ember/10 text-ember",
  };
  const label: Record<string, string> = {
    VERIFIED: "WE READ THIS OURSELVES",
    PAGE_VERIFIED: "PAGE CONFIRMED",
    SYNDICATED: "VIA NEWS WIRE",
    UNREACHABLE: "SITE BLOCKED US",
  };
  const text: Record<string, string> = {
    VERIFIED: "We opened the government publication and read this figure ourselves.",
    PAGE_VERIFIED: "We confirmed the dataset page exists; we have not pulled the numbers from it yet.",
    SYNDICATED: "Read from an official statement carried by a news wire, not the publisher's own page.",
    UNREACHABLE: "This government site would not load for us.",
  };
  return (
    <span
      title={text[status] ?? status}
      className={`whitespace-nowrap rounded-full border px-2.5 py-0.5 font-mono text-[11px] font-semibold tracking-wide ${
        map[status] ?? "border-line-strong bg-panel2 text-text-muted"
      }`}
    >
      {label[status] ?? status.replace("_", " ")}
    </span>
  );
}

/** How long ago an ISO timestamp was, in the roughest unit that still reads clearly. */
function timeAgo(iso: string): string {
  const minutes = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  const days = Math.round(hours / 24);
  return `${days} day${days === 1 ? "" : "s"} ago`;
}

/** Short, honest reasons a figure isn't live — matched to the underlying source. */
const PINNED_HINT: Record<string, string> = {
  cbuae_annual_2025_licensees: "from a PDF report",
  cbuae_markets_q4_2025: "from a PDF report",
  cbuae_cb_register: "from a PDF report",
  cma_licensed_companies: "from a web page, by hand",
  cma_market_stats_2025: "from a news wire",
  bayanat_cbuae_series: "no confirmed source yet",
  dubai_pulse_pilot_volume: "no access key set up",
};

/**
 * Provenance chip for one government figure: whether it was just fetched
 * live, served from a saved copy, or is a fixed number because neither
 * worked. Every figure on this dashboard shows one of these three, honestly.
 */
export function FreshnessChip({
  freshness,
}: {
  freshness?: { source_key: string; status: string; fetched_at: string; cache_age_days: number | null } | null;
}) {
  if (!freshness) return null;
  const { status } = freshness;

  const cacheDays = Math.max(1, Math.round(freshness.cache_age_days ?? 0));
  const text =
    status === "LIVE" ? `LIVE · fetched ${timeAgo(freshness.fetched_at)}`
    : status === "CACHED" ? `CACHED · ${cacheDays} day${cacheDays === 1 ? "" : "s"} old`
    : `PINNED · ${PINNED_HINT[freshness.source_key] ?? "not live right now"}`;

  const cls =
    status === "LIVE" ? "border-band-low/40 bg-band-low/10 text-band-low"
    : status === "CACHED" ? "border-line-strong bg-panel2 text-text-secondary"
    : "border-band-mid/40 bg-band-mid/10 text-band-mid";

  const title =
    status === "LIVE" ? `Fetched just now from ${freshness.source_key.replace(/_/g, " ")}.`
    : status === "CACHED" ? "The live site didn't answer, so this is the last copy we successfully saved."
    : "Neither the live site nor a saved copy was available, so this is a fixed, hand-checked number.";

  return (
    <span
      title={title}
      className={`whitespace-nowrap rounded-full border px-2.5 py-0.5 font-mono text-[11px] font-semibold tracking-wide ${cls}`}
    >
      {text}
    </span>
  );
}

const METER_COLOR: Record<string, string> = {
  CRITICAL: "bg-ember",
  HIGH: "bg-band-high",
  MEDIUM: "bg-band-mid",
  LOW: "bg-band-low",
};

export function Meter({ pct, tone = "violet" }: { pct: number; tone?: string }) {
  const w = Math.max(0, Math.min(100, pct));
  const bar = METER_COLOR[tone] ?? "bg-volt";
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-sunken">
      <div className={`h-full rounded-full ${bar}`} style={{ width: `${w}%` }} />
    </div>
  );
}

/** Shown when the backend is not running — never a blank screen in front of a judge. */
export function Offline({ detail }: { detail: string }) {
  return (
    <div className="rounded-[14px] border border-band-mid/40 bg-band-mid/10 p-5 text-[14px] leading-relaxed">
      <p className="font-semibold text-band-mid">This demo isn&apos;t connected to its backend.</p>
      <p className="mt-1 text-text-secondary">
        Start everything with <code className="font-mono text-volt">make run</code>, or start just
        the main service with{" "}
        <code className="font-mono text-volt">
          uvicorn marsad_core.main:app --port 8000
        </code>
        .
      </p>
      <p className="mt-1.5 font-mono text-[12.5px] text-text-faint">{detail}</p>
    </div>
  );
}
