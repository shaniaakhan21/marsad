import type { ReactNode } from "react";

/** Sticky console header: mono eyebrow, display headline, lede, right-aligned actions. */
export function PageHeader({
  eyebrow, title, lede, actions,
}: { eyebrow: string; title: ReactNode; lede?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="sticky top-0 z-10 border-b border-line bg-ink/90 px-8 py-7 backdrop-blur-md backdrop-saturate-150">
      <div className="flex flex-wrap items-start justify-between gap-6">
        <div className="max-w-3xl">
          <p className="font-mono text-[12px] font-semibold uppercase tracking-[0.12em] text-volt">
            / {eyebrow}
          </p>
          <h1 className="mt-2 font-display text-[32px] font-semibold leading-[1.12] tracking-[-0.02em] text-text-primary">
            {title}
          </h1>
          {lede && (
            <div className="mt-3 max-w-2xl text-[15.5px] leading-relaxed text-text-secondary">
              {lede}
            </div>
          )}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2.5 pt-1">{actions}</div>}
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
    "inline-flex items-center gap-2 rounded-[8px] px-4 py-2.5 font-mono text-[12.5px] font-semibold uppercase tracking-[0.05em] " +
    "transition duration-150 ease-console disabled:opacity-50 disabled:pointer-events-none " +
    "active:translate-y-[1px] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-volt/40 focus-visible:ring-offset-2 focus-visible:ring-offset-ink";
  const variants: Record<string, string> = {
    primary:
      "border border-volt-hover bg-volt text-white shadow-signature hover:bg-volt-hover active:shadow-signature-press",
    secondary:
      "border border-line-strong bg-panel text-text-secondary shadow-card hover:border-volt hover:text-volt",
  };
  return (
    <button onClick={onClick} disabled={disabled} className={`${base} ${variants[variant]}`}>
      {children}
    </button>
  );
}
