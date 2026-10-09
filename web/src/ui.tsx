import {
  createContext, useCallback, useContext, useEffect, useRef, useState,
  type ButtonHTMLAttributes, type ReactNode,
} from "react";
import { AlertTriangle, CheckCircle2, Info, Loader2, X } from "lucide-react";
import type { Bucket } from "./api";

export const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(" ");

/* ---------- tones ---------- */

export type Tone = "ok" | "warn" | "bad" | "info" | "mute" | "brand";
const TONE: Record<Tone, string> = {
  ok: "bg-ok-soft text-ok",
  warn: "bg-warn-soft text-warn",
  bad: "bg-bad-soft text-bad",
  info: "bg-info-soft text-info",
  mute: "bg-mute-soft text-mute",
  brand: "bg-brand-soft text-brand",
};
export const TONE_BAR: Record<Tone, string> = {
  ok: "bg-ok", warn: "bg-warn", bad: "bg-bad", info: "bg-info", mute: "bg-mute", brand: "bg-brand",
};

export const BUCKET: Record<Bucket, { label: string; tone: Tone; hint: string }> = {
  high: { label: "Auto-filled", tone: "ok", hint: "High confidence, filled in for you" },
  verified: { label: "Confirmed", tone: "info", hint: "A person confirmed or corrected this" },
  medium: { label: "Please confirm", tone: "warn", hint: "Likely right, needs a quick check" },
  low: { label: "Review", tone: "bad", hint: "Low confidence, check carefully" },
  missing: { label: "Fill in", tone: "mute", hint: "Nothing found in the documents" },
};

/* ---------- Button ---------- */

type Variant = "primary" | "secondary" | "ghost" | "danger";
interface BtnProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: "sm" | "md";
  loading?: boolean;
  icon?: ReactNode;
}
const VARIANT: Record<Variant, string> = {
  primary: "bg-brand text-brand-ink hover:brightness-110 shadow-card",
  secondary: "bg-surface text-ink border border-line-strong hover:bg-surface-2",
  ghost: "text-ink-2 hover:bg-mute-soft hover:text-ink",
  danger: "bg-bad text-white hover:brightness-110",
};

export function Button({ variant = "secondary", size = "md", loading, icon, children, className, disabled, ...rest }: BtnProps) {
  return (
    <button
      {...rest}
      disabled={disabled || loading}
      className={cx(
        "inline-flex items-center justify-center gap-2 rounded-lg font-medium whitespace-nowrap transition select-none",
        "disabled:opacity-50 disabled:cursor-not-allowed active:scale-[0.98]",
        size === "md" ? "h-10 px-4 text-sm" : "h-8 px-3 text-[13px]",
        VARIANT[variant],
        className,
      )}
    >
      {loading ? <Loader2 size={16} className="anim-spin" /> : icon}
      {children}
    </button>
  );
}

/* ---------- Badge / Card / Stat ---------- */

export function Badge({ tone = "mute", children, className }: { tone?: Tone; children: ReactNode; className?: string }) {
  return (
    <span className={cx("inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold", TONE[tone], className)}>
      {children}
    </span>
  );
}

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <section className={cx("rounded-xl border border-line bg-surface shadow-card", className)}>{children}</section>;
}

export function Stat({ label, value, sub, tone = "mute", icon }: { label: string; value: ReactNode; sub?: ReactNode; tone?: Tone; icon?: ReactNode }) {
  return (
    <Card className="p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-xs font-medium uppercase tracking-wide text-ink-3">{label}</div>
          <div className="mt-1 text-2xl font-semibold tabular-nums text-ink">{value}</div>
          {sub && <div className="mt-0.5 text-xs text-ink-2">{sub}</div>}
        </div>
        {icon && <div className={cx("grid h-9 w-9 shrink-0 place-items-center rounded-lg", TONE[tone])}>{icon}</div>}
      </div>
    </Card>
  );
}

export function Meter({ value, tone, label }: { value: number; tone: Tone; label?: string }) {
  const pct = Math.max(0, Math.min(1, value)) * 100;
  return (
    <div className="flex items-center gap-2" role="meter" aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100} aria-label={label}>
      <div className="h-1.5 w-20 overflow-hidden rounded-full bg-mute-soft">
        <div className={cx("h-full rounded-full transition-all duration-500", TONE_BAR[tone])} style={{ width: `${pct}%` }} />
      </div>
      <span className="w-9 text-xs tabular-nums text-ink-2">{pct.toFixed(0)}%</span>
    </div>
  );
}

/* ---------- Segmented control ---------- */

export function Segmented<T extends string | number>({
  value, onChange, options, label, full,
}: { value: T; onChange: (v: T) => void; options: { value: T; label: ReactNode }[]; label?: string; full?: boolean }) {
  return (
    <div role="radiogroup" aria-label={label} className={cx("rounded-lg border border-line bg-surface-2 p-0.5", full ? "flex" : "inline-flex")}>
      {options.map((o) => (
        <button
          key={String(o.value)}
          role="radio"
          aria-checked={o.value === value}
          onClick={() => onChange(o.value)}
          className={cx(
            "h-8 rounded-md px-3 text-[13px] font-medium transition", full && "flex-1",
            o.value === value ? "bg-surface text-ink shadow-card" : "text-ink-2 hover:text-ink",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Tabs<T extends string>({ value, onChange, tabs }: { value: T; onChange: (v: T) => void; tabs: { id: T; label: ReactNode; count?: number }[] }) {
  return (
    <div role="tablist" className="scroll-thin flex gap-1 overflow-x-auto border-b border-line">
      {tabs.map((t) => (
        <button
          key={t.id}
          role="tab"
          aria-selected={t.id === value}
          onClick={() => onChange(t.id)}
          className={cx(
            "-mb-px flex h-11 shrink-0 items-center gap-2 border-b-2 px-4 text-sm font-medium whitespace-nowrap transition",
            t.id === value ? "border-brand text-ink" : "border-transparent text-ink-2 hover:text-ink",
          )}
        >
          {t.label}
          {t.count !== undefined && t.count > 0 && (
            <span className="rounded-full bg-warn-soft px-1.5 text-[11px] font-semibold text-warn">{t.count}</span>
          )}
        </button>
      ))}
    </div>
  );
}

export function Switch({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <label className="inline-flex cursor-pointer items-center gap-2.5 text-sm text-ink-2">
      <button
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={cx("relative h-6 w-10 rounded-full transition", checked ? "bg-brand" : "bg-line-strong")}
      >
        <span className={cx("absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-all", checked ? "left-[18px]" : "left-0.5")} />
      </button>
      {label}
    </label>
  );
}

/* ---------- Skeleton / Empty / Error ---------- */

export const Skeleton = ({ className }: { className?: string }) => (
  <div className={cx("animate-pulse rounded-lg bg-mute-soft", className)} />
);

export function EmptyState({ icon, title, children, action }: { icon: ReactNode; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center px-6 py-14 text-center">
      <div className="mb-4 grid h-12 w-12 place-items-center rounded-2xl bg-brand-soft text-brand">{icon}</div>
      <h3 className="text-base font-semibold">{title}</h3>
      {children && <p className="mt-1 max-w-md text-sm text-ink-2">{children}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function Notice({ tone = "info", title, children }: { tone?: Tone; title?: string; children?: ReactNode }) {
  const Icon = tone === "ok" ? CheckCircle2 : tone === "bad" || tone === "warn" ? AlertTriangle : Info;
  return (
    <div className={cx("flex gap-3 rounded-lg px-4 py-3 text-sm", TONE[tone])} role={tone === "bad" ? "alert" : "status"}>
      <Icon size={18} className="mt-0.5 shrink-0" />
      <div className="min-w-0">
        {title && <div className="font-semibold">{title}</div>}
        {children && <div className={cx(title && "mt-0.5", "text-ink-2")}>{children}</div>}
      </div>
    </div>
  );
}

/* ---------- Toasts ---------- */

interface ToastItem { id: number; tone: "ok" | "bad" | "info"; text: string }
const ToastCtx = createContext<(tone: ToastItem["tone"], text: string) => void>(() => {});
export const useToast = () => useContext(ToastCtx);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const next = useRef(1);
  const push = useCallback((tone: ToastItem["tone"], text: string) => {
    const id = next.current++;
    setItems((l) => [...l, { id, tone, text }]);
    setTimeout(() => setItems((l) => l.filter((t) => t.id !== id)), tone === "bad" ? 7000 : 4000);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed inset-x-0 bottom-4 z-50 flex flex-col items-center gap-2 px-4" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className="anim-toast pointer-events-auto flex max-w-md items-start gap-3 rounded-xl border border-line bg-surface px-4 py-3 text-sm shadow-pop">
            {t.tone === "ok" ? <CheckCircle2 size={18} className="mt-0.5 shrink-0 text-ok" /> :
              t.tone === "bad" ? <AlertTriangle size={18} className="mt-0.5 shrink-0 text-bad" /> :
                <Info size={18} className="mt-0.5 shrink-0 text-info" />}
            <span className="min-w-0 break-words">{t.text}</span>
            <button className="-mr-1 ml-1 rounded p-0.5 text-ink-3 hover:text-ink" aria-label="Dismiss" onClick={() => setItems((l) => l.filter((x) => x.id !== t.id))}>
              <X size={14} />
            </button>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

/* ---------- data hook ---------- */

export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let live = true;
    setLoading(true);
    fn()
      .then((d) => { if (live) { setData(d); setError(null); } })
      .catch((e: Error) => { if (live) setError(e.message); })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  return { data, error, loading, reload: () => setTick((t) => t + 1), setData };
}

export function useDebounced<T>(value: T, ms = 250) {
  const [v, setV] = useState(value);
  useEffect(() => { const t = setTimeout(() => setV(value), ms); return () => clearTimeout(t); }, [value, ms]);
  return v;
}

export const pct = (x: number | null | undefined, d = 0) => (x == null ? "—" : `${(x * 100).toFixed(d)}%`);

export function confTone(c: number | null | undefined, hi = 0.8, med = 0.5): Tone {
  if (c == null) return "mute";
  return c >= hi ? "ok" : c >= med ? "warn" : "bad";
}

export function download(name: string, text: string, mime = "text/csv") {
  const url = URL.createObjectURL(new Blob([text], { type: mime }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}
