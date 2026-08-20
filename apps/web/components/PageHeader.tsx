import type { ReactNode } from "react";

/** Sticky console header: mono eyebrow, display headline, lede, right-aligned actions. */
export function PageHeader({
  eyebrow, title, lede, actions,
}: { eyebrow: string; title: ReactNode; lede?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="sticky top-0 z-10 border-b border-line bg-ink/86 px-8 py-6 backdrop-blur-[14px] backdrop-saturate-150">
      <div className="flex flex-wrap items-start justify-between gap-6">
        <div className="max-w-2xl">
          <p className="font-mono text-[11px] font-semibold uppercase tracking-[0.13em] text-text-muted">
            / {eyebrow}
          </p>
          <h1 className="mt-1.5 font-display text-[28px] font-extrabold leading-[1.1] tracking-[-0.035em] text-text-primary">
            {title}
          </h1>
          {lede && (
            <div className="mt-2 max-w-xl text-[13px] leading-relaxed text-text-secondary">
              {lede}
            </div>
          )}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2 pt-1">{actions}</div>}
      </div>
    </header>
  );
}

export function ActionButton({
  children, onClick, disabled, variant = "primary",
}: {
  children: ReactNode; onClick?: () => void; disabled?: boolean;
  variant?: "primary" | "secondary";
}) {
  const base =
    "rounded-[8px] px-4 py-2 font-mono text-[11px] font-semibold uppercase tracking-[0.06em] " +
    "transition-transform duration-150 ease-console disabled:opacity-40 disabled:pointer-events-none " +
    "active:translate-x-[2px] active:translate-y-[2px]";
  const variants: Record<string, string> = {
    primary:
      "border-2 border-ink bg-volt text-ink shadow-signature hover:bg-volt-hover active:shadow-signature-press",
    secondary:
      "border border-line bg-panel text-text-secondary hover:border-volt/50 hover:text-text-primary",
  };
  return (
    <button onClick={onClick} disabled={disabled} className={`${base} ${variants[variant]}`}>
      {children}
    </button>
  );
}
