import { useEffect, useState } from "react";
import { Check, FileJson, Layers, Minus, Search, TriangleAlert, UserRound, X } from "lucide-react";
import { api, type ExplorerSeller, type FieldKey } from "../api";
import { Badge, Card, EmptyState, Meter, Notice, Skeleton, Switch, confTone, cx, useAsync, useDebounced } from "../ui";
import { LinkButton, PageHeader } from "./shared";

const ROWS: { key: FieldKey; label: string; truth: boolean }[] = [
  { key: "company_name", label: "Company / trade name", truth: true },
  { key: "gstin", label: "GSTIN", truth: false },
  { key: "legal_status", label: "Legal status", truth: true },
  { key: "city", label: "City", truth: true },
  { key: "state", label: "State", truth: true },
  { key: "pincode", label: "Pincode", truth: true },
];

export default function Explorer() {
  const [q, setQ] = useState("");
  const dq = useDebounced(q.trim(), 200);
  const list = useAsync(() => api.explorerList(dq), [dq]);
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    if (!selected && list.data?.sellers.length) setSelected(list.data.sellers[0].id);
  }, [list.data, selected]);

  return (
    <>
      <PageHeader
        title="Seller explorer"
        subtitle="Pick any of the backtested sellers and compare each predicted field with IndiaMART's verified answer."
      />
      <div className="grid grid-cols-[minmax(0,1fr)] items-start gap-6 lg:grid-cols-[300px_minmax(0,1fr)]">
        <Card className="overflow-hidden lg:sticky lg:top-6">
          <div className="border-b border-line p-3">
            <div className="relative">
              <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-3" />
              <input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Search GLID"
                inputMode="numeric"
                aria-label="Search sellers by GLID"
                className="h-10 w-full rounded-lg border border-line-strong bg-surface-2 pl-9 pr-3 text-sm outline-none focus:border-brand"
              />
            </div>
            <div className="mt-2 text-xs text-ink-3">
              {list.data ? `${list.data.total.toLocaleString()} sellers${dq ? " match" : ""} · most documents first` : "Loading…"}
            </div>
          </div>
          <ul className="scroll-thin max-h-[60vh] overflow-y-auto p-2 lg:max-h-[calc(100vh-14rem)]">
            {list.loading && !list.data && [0, 1, 2, 3, 4].map((i) => <li key={i} className="p-1"><Skeleton className="h-11" /></li>)}
            {list.data?.sellers.map((s) => (
              <li key={s.id}>
                <button
                  onClick={() => setSelected(s.id)}
                  aria-current={selected === s.id}
                  className={cx("flex w-full items-center justify-between gap-3 rounded-lg px-3 py-2.5 text-left transition", selected === s.id ? "bg-brand-soft" : "hover:bg-mute-soft")}
                >
                  <span className="font-mono text-[13px] font-medium">{s.id}</span>
                  <span className="flex items-center gap-2 text-xs text-ink-3">
                    {s.flags > 0 && <TriangleAlert size={14} className="text-bad" aria-label="Risk flags" />}
                    {s.docs} docs
                  </span>
                </button>
              </li>
            ))}
            {list.data?.sellers.length === 0 && <li className="px-3 py-8 text-center text-sm text-ink-3">No seller with that GLID.</li>}
          </ul>
        </Card>

        {selected ? <Detail key={selected} id={selected} /> : (
          <Card><EmptyState icon={<Search size={22} />} title="Pick a seller">Choose a GLID on the left to see its profile.</EmptyState></Card>
        )}
      </div>
    </>
  );
}

function Detail({ id }: { id: string }) {
  const { data, error, loading } = useAsync(() => api.explorerSeller(id), [id]);
  const [truth, setTruth] = useState(true);
  if (loading && !data) return <Skeleton className="h-[560px]" />;
  if (error || !data) return <Notice tone="bad" title="Could not load this seller">{error}</Notice>;
  const hasTruth = Object.keys(data.truth).length > 0;

  return (
    <div className="min-w-0 space-y-4">
      <Card className="p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="text-xs font-medium uppercase tracking-wide text-ink-3">Seller GLID</div>
            <h2 className="mt-0.5 font-mono text-2xl font-semibold">{data.id}</h2>
            <div className="mt-2 flex flex-wrap gap-1.5">
              <Badge tone="brand">{data.doc_count} documents</Badge>
              {data.doc_types.map((t) => <Badge key={t}>{t}</Badge>)}
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            {hasTruth && <Switch checked={truth} onChange={setTruth} label="Show answer key" />}
            <LinkButton href={`/api/explorer/sellers/${id}/profile.json`} icon={<FileJson size={16} />}>Profile JSON</LinkButton>
          </div>
        </div>
        {data.risk_flags.length > 0 && <div className="mt-4"><Notice tone="warn" title="Risk flags">{data.risk_flags.join(", ")}</Notice></div>}
      </Card>

      <Card className="overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-sm">
            <thead className="bg-surface-2 text-left text-xs uppercase tracking-wide text-ink-3">
              <tr>
                <th className="px-5 py-3 font-medium">Field</th>
                <th className="px-3 py-3 font-medium">Predicted</th>
                <th className="px-3 py-3 font-medium">Confidence</th>
                <th className="px-3 py-3 font-medium">Sources</th>
                {truth && hasTruth && <th className="px-5 py-3 font-medium">Answer key</th>}
              </tr>
            </thead>
            <tbody>
              {ROWS.map((r) => <Row key={r.key} data={data} k={r.key} label={r.label} showTruth={truth && hasTruth} hasKey={r.truth} />)}
            </tbody>
          </table>
        </div>
        {data.raw_address && <div className="border-t border-line px-5 py-3 text-xs text-ink-2"><b className="text-ink-3">Raw address text:</b> {data.raw_address}</div>}
      </Card>

      <div className="grid grid-cols-[minmax(0,1fr)] gap-4 xl:grid-cols-2">
        <Card className="p-5">
          <h3 className="flex items-center gap-2 text-sm font-semibold"><UserRound size={16} className="text-ink-3" /> People and roles</h3>
          <p className="mt-1 text-xs text-ink-3">Not predicted. These come from the authoritative GST registry lookup once the GSTIN is resolved.</p>
          <dl className="mt-3 space-y-2 text-sm">
            <div><dt className="text-xs text-ink-3">Partner / owner name(s)</dt><dd className="font-medium">{data.truth.partners?.trim() || "—"}</dd></div>
            <div><dt className="text-xs text-ink-3">Designation</dt><dd className="font-medium">{data.truth.designation || "—"}</dd></div>
          </dl>
        </Card>

        <Card className="overflow-hidden">
          <h3 className="flex items-center gap-2 px-5 pt-5 text-sm font-semibold"><Layers size={16} className="text-ink-3" /> Suggested categories</h3>
          {data.categories.length === 0 ? (
            <p className="px-5 pb-5 pt-2 text-sm text-ink-3">No category signal for this seller.</p>
          ) : (
            <ul className="mt-2 divide-y divide-line">
              {data.categories.map((c) => (
                <li key={c.category} className="flex items-center justify-between gap-3 px-5 py-2.5 text-sm">
                  <span className="min-w-0"><span className="block truncate font-medium">{c.category}</span><span className="block truncate text-xs text-ink-3">{c.group}</span></span>
                  <span className="flex shrink-0 items-center gap-2 tabular-nums text-ink-2">
                    {c.confidence.toFixed(2)}
                    {truth && hasTruth && (c.real ? <Badge tone="ok"><Check size={12} /> real</Badge> : <span className="w-12" />)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      {data.products.length > 0 && (
        <Card className="overflow-hidden">
          <h3 className="px-5 pt-5 text-sm font-semibold">Products seen on invoices</h3>
          <div className="scroll-thin mt-2 overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs uppercase tracking-wide text-ink-3">
                <tr>{Object.keys(data.products[0]).map((h) => <th key={h} className="px-5 py-2 font-medium">{h.replace(/_/g, " ")}</th>)}</tr>
              </thead>
              <tbody>
                {data.products.map((p, i) => (
                  <tr key={i} className="border-t border-line">
                    {Object.values(p).map((v, j) => <td key={j} className="px-5 py-2.5">{v == null ? "—" : String(v)}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}

function Row({ data, k, label, showTruth, hasKey }: { data: ExplorerSeller; k: FieldKey; label: string; showTruth: boolean; hasKey: boolean }) {
  const f = data.fields[k];
  const t = data.truth[k] ?? null;
  const match = f.value && t ? f.value.trim().toLowerCase() === t.trim().toLowerCase() : null;
  return (
    <tr className="border-t border-line align-top">
      <td className="px-5 py-3 font-medium">{label}</td>
      <td className={cx("px-3 py-3 font-semibold", (k === "gstin" || k === "pincode") && "font-mono")}>{f.value ?? <span className="font-normal text-ink-3">—</span>}</td>
      <td className="px-3 py-3">
        {f.value ? <Meter value={f.confidence} tone={confTone(f.confidence)} label={`${label} confidence`} /> : <span className="text-ink-3">—</span>}
        {f.calibrated && <div className="mt-0.5 text-[11px] text-ink-3">raw {f.raw_confidence.toFixed(2)}</div>}
      </td>
      <td className="px-3 py-3 text-xs text-ink-2">{f.sources.length ? f.sources.join(", ") : "no source"}</td>
      {showTruth && (
        <td className="px-5 py-3">
          {!hasKey ? <span className="text-xs text-ink-3">not checkable (privacy)</span> : (
            <span className="flex items-center gap-2">
              {match === true && <Check size={16} className="shrink-0 text-ok" aria-label="matches" />}
              {match === false && <X size={16} className="shrink-0 text-bad" aria-label="does not match" />}
              {match === null && <Minus size={16} className="shrink-0 text-ink-3" aria-label="no comparison" />}
              <span className={cx(match === false && "text-bad")}>{t ?? "—"}</span>
            </span>
          )}
        </td>
      )}
    </tr>
  );
}
