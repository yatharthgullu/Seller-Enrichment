import { useState } from "react";
import { Boxes, Database, FileJson, FileSpreadsheet, Gauge, Layers, ShieldCheck, Target } from "lucide-react";
import { api } from "../api";
import { Card, Notice, Skeleton, Stat, TONE_BAR, confTone, cx, pct, useAsync, useDebounced } from "../ui";
import { LinkButton, PageHeader } from "./shared";

export default function Accuracy() {
  const [threshold, setThreshold] = useState(0.8);
  const t = useDebounced(threshold, 200);
  const { data, error, loading } = useAsync(() => api.accuracy(t), [t]);

  if (error) return <Notice tone="bad" title="Could not load the backtest">{error}</Notice>;
  if (!data && loading) {
    return <div className="space-y-4"><Skeleton className="h-9 w-72" /><Skeleton className="h-72" /><Skeleton className="h-72" /></div>;
  }
  if (!data?.loaded) {
    return <Notice tone="warn" title="No backtest results found">Run the pipeline to generate outputs/metrics_summary.json.</Notice>;
  }
  const th = data.threshold;

  return (
    <>
      <PageHeader
        title="Accuracy"
        subtitle={`Every field is backtested against IndiaMART's verified records for ${data.sellers.toLocaleString()} sellers. Nothing here uses the answer key to predict.`}
        actions={
          <>
            <LinkButton href="/api/accuracy/predictions.csv" icon={<FileSpreadsheet size={16} />}>Predictions CSV</LinkButton>
            <LinkButton href="/api/accuracy/profiles.json" icon={<FileJson size={16} />}>Full profiles JSON</LinkButton>
          </>
        }
      />

      <div className="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Field coverage" value={pct(data.coverage.rate, 1)} sub={`${data.coverage.avg_fields} of ${data.coverage.total_fields} fields filled on average`} icon={<Database size={18} />} tone="brand" />
        <Stat label="Category top-5 precision" value={pct(data.category_top5.rate, 1)} sub={`${data.category_top5.n} sellers with a suggestion`} icon={<Layers size={18} />} tone="warn" />
        <Stat label="Catalog gaps fillable" value={data.catalog.sellers_with_catalog_gaps_and_invoice_products} sub={`${data.catalog.products_price_fillable} priced line items recovered`} icon={<Boxes size={18} />} tone="ok" />
        <Stat label="Fields auto-acceptable" value={pct(th.field_pass_rate, 1)} sub={`at ≥ ${th.value.toFixed(2)} confidence`} icon={<ShieldCheck size={18} />} tone="ok" />
      </div>

      <div className="grid grid-cols-[minmax(0,1fr)] items-start gap-6 xl:grid-cols-2">
        <Card className="p-5">
          <h2 className="flex items-center gap-2 text-base font-semibold"><Target size={18} className="text-ink-3" /> Match rate against the answer key</h2>
          <p className="mt-1 text-sm text-ink-2">Share of sellers where the predicted value matches IndiaMART's verified record.</p>
          <ul className="mt-5 space-y-4">
            {data.headline.map((h) => (
              <li key={h.key}>
                <div className="mb-1.5 flex items-baseline justify-between gap-3">
                  <span className="text-sm font-medium">{h.label}</span>
                  <span className="text-sm font-semibold tabular-nums">{pct(h.rate, 1)}</span>
                </div>
                <div className="h-2.5 overflow-hidden rounded-full bg-mute-soft" role="meter" aria-valuenow={Math.round(h.rate * 100)} aria-valuemin={0} aria-valuemax={100} aria-label={h.label}>
                  <div className={cx("h-full rounded-full transition-all duration-700", TONE_BAR[confTone(h.rate, 0.85, 0.7)])} style={{ width: `${h.rate * 100}%` }} />
                </div>
                <div className="mt-1 text-xs text-ink-3">{h.note}</div>
              </li>
            ))}
          </ul>
        </Card>

        <Card className="p-5">
          <h2 className="flex items-center gap-2 text-base font-semibold"><Gauge size={18} className="text-ink-3" /> Confidence threshold explorer</h2>
          <p className="mt-1 text-sm text-ink-2">
            Scores are calibrated: a threshold here means what it says. Move it to see how much could be auto-accepted. A missing field never counts as a pass.
          </p>

          <div className="mt-5 rounded-xl bg-surface-2 p-4">
            <div className="mb-2 flex items-baseline justify-between">
              <label htmlFor="thr" className="text-sm font-medium">Auto-accept at confidence of at least</label>
              <output className="text-xl font-semibold tabular-nums">{threshold.toFixed(2)}</output>
            </div>
            <input
              id="thr"
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={threshold}
              onChange={(e) => setThreshold(Number(e.target.value))}
              className="h-2 w-full cursor-pointer accent-[var(--brand)]"
            />
            <div className="mt-1 flex justify-between text-[11px] text-ink-3"><span>0.00 accept everything</span><span>1.00 accept nothing</span></div>
          </div>

          <div className="mt-5 grid grid-cols-2 gap-3">
            <div className="rounded-xl border border-line p-3">
              <div className="text-xs text-ink-3">Sellers with every field above</div>
              <div className="mt-0.5 text-xl font-semibold tabular-nums text-ok">{th.sellers_all_pass.toLocaleString()}</div>
            </div>
            <div className="rounded-xl border border-line p-3">
              <div className="text-xs text-ink-3">Sellers needing a review</div>
              <div className="mt-0.5 text-xl font-semibold tabular-nums text-warn">{th.sellers_need_review.toLocaleString()}</div>
            </div>
          </div>

          <ul className="mt-5 space-y-3">
            {th.per_field.map((f) => (
              <li key={f.key} className="grid grid-cols-[110px_1fr_52px] items-center gap-3 text-sm">
                <span className="text-ink-2">{f.label}</span>
                <div className="h-2 overflow-hidden rounded-full bg-mute-soft">
                  <div className={cx("h-full rounded-full transition-all duration-300", TONE_BAR.brand)} style={{ width: `${f.rate * 100}%` }} />
                </div>
                <span className="text-right tabular-nums">{pct(f.rate)}</span>
              </li>
            ))}
          </ul>
          <p className="mt-4 text-xs text-ink-3">
            Covers the five independently validated fields. GSTIN has no full-number ground truth to calibrate against, so it is tracked separately in the export.
          </p>
        </Card>
      </div>
    </>
  );
}
