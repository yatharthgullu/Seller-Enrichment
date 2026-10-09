import type { ReactNode } from "react";
import { cx } from "../ui";

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="mt-1 max-w-3xl text-sm text-ink-2">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

/** An <a download> that looks like a Button. */
export function LinkButton({ href, children, icon, className }: { href: string; children: ReactNode; icon?: ReactNode; className?: string }) {
  return (
    <a
      href={href}
      download
      className={cx(
        "inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-line-strong bg-surface px-4 text-sm font-medium text-ink transition hover:bg-surface-2 active:scale-[0.98]",
        className,
      )}
    >
      {icon}
      {children}
    </a>
  );
}
