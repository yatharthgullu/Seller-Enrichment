import { useEffect, useState } from "react";
import { BarChart3, CheckCheck, FileSearch, PhoneCall, Radio, Upload } from "lucide-react";
import { api } from "./api";
import { cx, useAsync } from "./ui";
import { ThemeToggle } from "./theme";
import Enrich from "./views/Enrich";
import Accuracy from "./views/Accuracy";
import Explorer from "./views/Explorer";

type Route = "enrich" | "accuracy" | "explorer";
const NAV: { id: Route; label: string; hint: string; icon: typeof Upload }[] = [
  { id: "enrich", label: "Enrich sellers", hint: "Upload documents, confirm fields", icon: Upload },
  { id: "accuracy", label: "Accuracy", hint: "Backtest on 3,000 sellers", icon: BarChart3 },
  { id: "explorer", label: "Seller explorer", hint: "Profile vs. answer key", icon: FileSearch },
];

const readRoute = (): Route => {
  const h = window.location.hash.replace(/^#\/?/, "").split("?")[0];
  return (NAV.find((n) => n.id === h)?.id ?? "enrich") as Route;
};

export default function App() {
  const [route, setRoute] = useState<Route>(readRoute);
  useEffect(() => {
    const on = () => setRoute(readRoute());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  const go = (r: Route) => { window.location.hash = `/${r}`; };
  const { data: meta, error } = useAsync(api.meta, []);

  return (
    <div className="flex min-h-full flex-col lg:flex-row">
      {/* Sidebar (desktop) */}
      <aside className="sticky top-0 z-20 hidden h-screen w-64 shrink-0 flex-col border-r border-line bg-surface lg:flex">
        <Brand />
        <nav className="flex-1 space-y-1 px-3 py-2" aria-label="Main">
          {NAV.map((n) => (
            <button
              key={n.id}
              onClick={() => go(n.id)}
              aria-current={route === n.id ? "page" : undefined}
              className={cx(
                "group flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left transition",
                route === n.id ? "bg-brand-soft text-brand" : "text-ink-2 hover:bg-mute-soft hover:text-ink",
              )}
            >
              <n.icon size={18} className="shrink-0" />
              <span className="min-w-0">
                <span className="block text-sm font-semibold leading-tight">{n.label}</span>
                <span className={cx("block truncate text-xs", route === n.id ? "text-brand/80" : "text-ink-3")}>{n.hint}</span>
              </span>
            </button>
          ))}
        </nav>
        <Status meta={meta} error={error} />
        <div className="flex items-center justify-between border-t border-line px-4 py-3 text-xs text-ink-3">Theme <ThemeToggle /></div>
      </aside>

      {/* Top bar (mobile / tablet) */}
      <header className="sticky top-0 z-20 border-b border-line bg-surface lg:hidden">
        <div className="flex items-center justify-between px-4"><Brand compact /><ThemeToggle /></div>
        <nav className="flex gap-1 overflow-x-auto px-3 pb-2" aria-label="Main">
          {NAV.map((n) => (
            <button
              key={n.id}
              onClick={() => go(n.id)}
              aria-current={route === n.id ? "page" : undefined}
              className={cx(
                "flex h-9 shrink-0 items-center gap-2 rounded-lg px-3 text-sm font-medium",
                route === n.id ? "bg-brand-soft text-brand" : "text-ink-2",
              )}
            >
              <n.icon size={16} />
              {n.label}
            </button>
          ))}
        </nav>
      </header>

      <main className="min-w-0 flex-1">
        <div className="mx-auto w-full max-w-[1400px] px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
          {error && (
            <div className="mb-4 rounded-lg bg-bad-soft px-4 py-3 text-sm text-bad" role="alert">{error}</div>
          )}
          {route === "enrich" && <Enrich meta={meta} />}
          {route === "accuracy" && <Accuracy />}
          {route === "explorer" && <Explorer />}
        </div>
      </main>
    </div>
  );
}

function Brand({ compact }: { compact?: boolean }) {
  return (
    <div className={cx("flex items-center gap-3", compact ? "h-14" : "h-16 px-5")}>
      <div className="grid h-9 w-9 place-items-center rounded-xl bg-brand text-brand-ink shadow-card"><CheckCheck size={20} /></div>
      <div className="leading-tight">
        <div className="text-[15px] font-semibold">Seller Enrichment</div>
        <div className="text-xs text-ink-3">Documents → verified profile</div>
      </div>
    </div>
  );
}

function Status({ meta, error }: { meta: Awaited<ReturnType<typeof api.meta>> | null; error: string | null }) {
  const row = (ok: boolean | undefined, label: string, icon: React.ReactNode) => (
    <div className="flex items-center gap-2.5 text-xs text-ink-2">
      <span className={cx("grid h-6 w-6 place-items-center rounded-md", ok ? "bg-ok-soft text-ok" : "bg-mute-soft text-mute")}>{icon}</span>
      <span className="flex-1">{label}</span>
      <span className={cx("h-2 w-2 rounded-full", ok ? "bg-ok" : "bg-line-strong")} aria-label={ok ? "connected" : "not set up"} />
    </div>
  );
  return (
    <div className="space-y-2.5 border-t border-line p-4">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-ink-3">Connections</div>
      {row(!error && !!meta, "Backend API", <Radio size={13} />)}
      {row(meta?.sarvam.fetch_ready, "Sarvam call results", <PhoneCall size={13} />)}
      {row(meta?.sarvam.webhook_ready, "Webhook (auto-delivery)", <Radio size={13} />)}
      {meta && !meta.sarvam.fetch_ready && (
        <p className="text-[11px] leading-snug text-warn">Add {meta.sarvam.missing.join(", ")} to .env</p>
      )}
    </div>
  );
}
