import { useEffect, useMemo, useRef, useState, type DragEvent } from "react";
import {
  Check, CheckCircle2, ClipboardCheck, Download, FileJson, FileSpreadsheet, FileUp, FlaskConical, Layers,
  ListChecks, Pencil, PhoneCall, Search, Sparkles, TriangleAlert, Users, X,
} from "lucide-react";
import { api, type FieldKey, type Meta, type SellerDetail, type SellerRow, type TriageField } from "../api";
import {
  BUCKET, Badge, Button, Card, EmptyState, Meter, Notice, Segmented, Skeleton, Stat, Tabs, TONE_BAR,
  confTone, cx, useAsync, useToast,
} from "../ui";
import { LinkButton, PageHeader } from "./shared";
import PhonePanel from "./PhonePanel";
import { SampleDataButton } from "./SampleData";

const FIELD_LABEL: Record<FieldKey, string> = {
  company_name: "Company name", gstin: "GSTIN", legal_status: "Legal status", city: "City", state: "State", pincode: "Pincode",
};

/** Deep links: #/enrich?seller=123&tab=phone */
function hashParam(name: string): string | null {
  const q = window.location.hash.split("?")[1];
  return q ? new URLSearchParams(q).get(name) : null;
}

export default function Enrich({ meta }: { meta: Meta | null }) {
  const summary = useAsync(api.enrich, []);
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<string | null>(() => hashParam("seller"));

  const s = summary.data;
  const sellers = s?.sellers ?? [];

  // keep a valid selection; prefer the first seller that still needs a person
  useEffect(() => {
    if (!sellers.length) return;
    if (!selected || !sellers.some((x) => x.id === selected)) {
      setSelected((sellers.find((x) => !x.ready) ?? sellers[0]).id);
    }
  }, [sellers, selected]);

  const ingest = async (run: () => Promise<unknown>, okText: string) => {
    setBusy(true);
    try {
      await run();
      setSelected(null);
      summary.reload();
      toast("ok", okText);
    } catch (e) {
      toast("bad", (e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const onFiles = (files: File[]) => {
    if (files.length) void ingest(() => api.upload(files), `Read ${files.length} file${files.length > 1 ? "s" : ""}`);
  };
  const onSample = () => void ingest(() => api.loadSample("ten"), "Loaded the 10-seller test set");

  if (summary.loading && !s) return <Loading />;

  if (!s?.loaded) {
    return (
      <>
        <PageHeader
          title="Enrich sellers"
          subtitle="Upload KYC documents and get every field back pre-filled with a confidence score, so people only touch what needs them."
          actions={<SampleDataButton hasPack={!!meta?.has_pack} />}
        />
        <Dropzone busy={busy} onFiles={onFiles} onSample={onSample} hasSample={!!meta?.has_pack} />
      </>
    );
  }

  const st = s.stats!;
  return (
    <>
      <PageHeader
        title="Enrich sellers"
        subtitle={
          <>
            Read {s.report!.docs_read} documents for {st.sellers} seller{st.sellers === 1 ? "" : "s"}
            {s.report!.skipped_type > 0 && ` · ${s.report!.skipped_type} skipped (unsupported type)`}
            {s.report!.skipped_json > 0 && ` · ${s.report!.skipped_json} skipped (no valid extraction)`}
          </>
        }
        actions={
          <>
            <SampleDataButton hasPack={!!meta?.has_pack} />
            <ReplaceButton busy={busy} onFiles={onFiles} />
            <LinkButton href="/api/enrich/export.csv" icon={<FileSpreadsheet size={16} />}>Export CSV</LinkButton>
            <LinkButton href="/api/enrich/export.json" icon={<FileJson size={16} />}>Export JSON</LinkButton>
          </>
        }
      />

      <div className="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Sellers" value={st.sellers} icon={<Users size={18} />} tone="brand" />
        <Stat label="Auto-filled or confirmed" value={`${st.auto_pct}%`} sub="of all fields" icon={<Sparkles size={18} />} tone="ok" />
        <Stat label="Fully ready" value={`${st.ready} / ${st.sellers}`} sub="sellers with nothing to check" icon={<CheckCircle2 size={18} />} tone="ok" />
        <Stat label="Fields needing a person" value={st.needs_person} sub="confirm, review or fill in" icon={<ListChecks size={18} />} tone="warn" />
      </div>

      <div className="grid grid-cols-[minmax(0,1fr)] items-start gap-6 lg:grid-cols-[320px_minmax(0,1fr)]">
        <SellerList sellers={sellers} selected={selected} onSelect={setSelected} />
        {selected && <SellerPane key={selected} id={selected} meta={meta} onChanged={summary.reload} />}
      </div>
    </>
  );
}

/* ------------------------------------------------------------------ */

function Loading() {
  return (
    <div className="space-y-4">
      <Skeleton className="h-9 w-64" />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-24" />)}</div>
      <Skeleton className="h-96" />
    </div>
  );
}

function ReplaceButton({ busy, onFiles }: { busy: boolean; onFiles: (f: File[]) => void }) {
  const ref = useRef<HTMLInputElement>(null);
  return (
    <>
      <input ref={ref} type="file" accept=".csv,.json" multiple hidden onChange={(e) => { onFiles([...(e.target.files ?? [])]); e.target.value = ""; }} />
      <Button loading={busy} icon={<FileUp size={16} />} onClick={() => ref.current?.click()}>Upload new files</Button>
    </>
  );
}

function Dropzone({ busy, onFiles, onSample, hasSample }: { busy: boolean; onFiles: (f: File[]) => void; onSample: () => void; hasSample: boolean }) {
  const ref = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const drop = (e: DragEvent) => { e.preventDefault(); setOver(false); onFiles([...e.dataTransfer.files]); };
  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_340px]">
      <div
        onDragOver={(e) => { e.preventDefault(); setOver(true); }}
        onDragLeave={() => setOver(false)}
        onDrop={drop}
        className={cx(
          "rounded-2xl border-2 border-dashed bg-surface transition",
          over ? "border-brand bg-brand-soft" : "border-line-strong",
        )}
      >
        <EmptyState
          icon={<FileUp size={24} />}
          title="Drop KYC documents here"
          action={
            <div className="flex flex-wrap justify-center gap-2">
              <input ref={ref} type="file" accept=".csv,.json" multiple hidden onChange={(e) => onFiles([...(e.target.files ?? [])])} />
              <Button variant="primary" loading={busy} icon={<FileUp size={16} />} onClick={() => ref.current?.click()}>Choose files</Button>
              {hasSample && <Button loading={busy} icon={<FlaskConical size={16} />} onClick={onSample}>Try the 10-seller test set</Button>}
            </div>
          }
        >
          CSV (like so_kyc_documents.csv) or JSON with an <code className="rounded bg-mute-soft px-1">llm_extraction</code> column. One seller or many.
        </EmptyState>
      </div>

      <Card className="p-5">
        <h3 className="text-sm font-semibold">How it works</h3>
        <ol className="mt-3 space-y-3 text-sm text-ink-2">
          {[
            ["Fuse", "Invoices, sign boards, Udyam certificates and cheques are read together."],
            ["Triage", "Each field is auto-filled, flagged to confirm, or marked to fill in."],
            ["Confirm", "Fix what is left yourself, or let the voice agent call the seller."],
          ].map(([t, d], i) => (
            <li key={t} className="flex gap-3">
              <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-brand-soft text-xs font-semibold text-brand">{i + 1}</span>
              <span><b className="text-ink">{t}.</b> {d}</span>
            </li>
          ))}
        </ol>
        {hasSample && (
          <div className="mt-5 border-t border-line pt-4">
            <div className="mb-2 text-xs font-medium uppercase tracking-wide text-ink-3">Test pack · 10 fictional sellers</div>
            <div className="flex flex-col gap-2">
              <LinkButton href="/api/enrich/samples/seller_enrichment_test_pack.zip" icon={<Download size={16} />} className="justify-start border-brand bg-brand-soft text-brand">All files (.zip)</LinkButton>
              <LinkButton href="/api/enrich/samples/sample_10_sellers.csv" icon={<Download size={16} />} className="justify-start">Upload file (CSV)</LinkButton>
              <LinkButton href="/api/enrich/samples/sample_10_sellers.json" icon={<Download size={16} />} className="justify-start">Same data (JSON)</LinkButton>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}

/* ------------------------------------------------------------------ */

function SellerList({ sellers, selected, onSelect }: { sellers: SellerRow[]; selected: string | null; onSelect: (id: string) => void }) {
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState<"all" | "check" | "ready">("all");
  const shown = useMemo(
    () => sellers.filter((x) => x.id.includes(q.trim()) && (filter === "all" || (filter === "ready") === x.ready)),
    [sellers, q, filter],
  );
  const nCheck = sellers.filter((x) => !x.ready).length;
  return (
    <Card className="overflow-hidden lg:sticky lg:top-6">
      <div className="space-y-3 border-b border-line p-3">
        <div className="relative">
          <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-3" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search GLID"
            aria-label="Search sellers by GLID"
            className="h-10 w-full rounded-lg border border-line-strong bg-surface-2 pl-9 pr-3 text-sm outline-none focus:border-brand"
          />
        </div>
        <Segmented
          full
          label="Filter sellers"
          value={filter}
          onChange={setFilter}
          options={[
            { value: "all", label: `All ${sellers.length}` },
            { value: "check", label: `To check ${nCheck}` },
            { value: "ready", label: `Ready ${sellers.length - nCheck}` },
          ]}
        />
      </div>
      <ul className="scroll-thin max-h-[60vh] overflow-y-auto p-2 lg:max-h-[calc(100vh-17rem)]">
        {shown.length === 0 && <li className="px-3 py-8 text-center text-sm text-ink-3">No sellers match.</li>}
        {shown.map((x) => (
          <li key={x.id}>
            <button
              onClick={() => onSelect(x.id)}
              aria-current={selected === x.id}
              className={cx(
                "flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left transition",
                selected === x.id ? "bg-brand-soft" : "hover:bg-mute-soft",
              )}
            >
              <span className={cx("grid h-8 w-8 shrink-0 place-items-center rounded-full", x.ready ? "bg-ok-soft text-ok" : "bg-warn-soft text-warn")}>
                {x.ready ? <Check size={16} /> : <span className="text-xs font-bold">{x.needs_attention}</span>}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate font-mono text-[13px] font-medium">{x.id}</span>
                <span className="block truncate text-xs text-ink-3">
                  {x.docs} doc{x.docs === 1 ? "" : "s"} · {x.ready ? "ready" : x.check.map((k) => FIELD_LABEL[k]).join(", ")}
                </span>
              </span>
              {x.risk_flags.length > 0 && <TriangleAlert size={15} className="shrink-0 text-bad" aria-label="Risk flags" />}
            </button>
          </li>
        ))}
      </ul>
    </Card>
  );
}

/* ------------------------------------------------------------------ */

type PaneTab = "fields" | "phone" | "categories";

function SellerPane({ id, meta, onChanged }: { id: string; meta: Meta | null; onChanged: () => void }) {
  const { data, error, loading, setData } = useAsync(() => api.seller(id), [id]);
  const [tab, setTab] = useState<PaneTab>(() => (["fields", "phone", "categories"].includes(hashParam("tab") ?? "") ? (hashParam("tab") as PaneTab) : "fields"));
  const toast = useToast();
  const [pending, setPending] = useState<string | null>(null);

  if (loading && !data) return <Skeleton className="h-[520px]" />;
  if (error || !data) return <Notice tone="bad" title="Could not load this seller">{error}</Notice>;

  const fields = data.triage.fields;
  const settled = fields.filter((f) => f.bucket === "high" || f.bucket === "verified").length;

  const save = async (f: TriageField, value: string) => {
    setPending(f.key);
    try {
      const next: SellerDetail = await api.correct(id, f.key, value);
      setData(next);
      onChanged();
      toast("ok", `${f.label} saved`);
      return true;
    } catch (e) {
      toast("bad", (e as Error).message);
      return false;
    } finally {
      setPending(null);
    }
  };

  return (
    <div className="min-w-0 space-y-4">
      <Card className="p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="text-xs font-medium uppercase tracking-wide text-ink-3">Seller GLID</div>
            <div className="mt-0.5 flex flex-wrap items-center gap-3">
              <h2 className="font-mono text-2xl font-semibold">{id}</h2>
              {data.triage.ready ? <Badge tone="ok"><CheckCircle2 size={13} /> Ready</Badge> : <Badge tone="warn">{data.triage.needs_attention} to check</Badge>}
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              <Layers size={14} className="text-ink-3" />
              {data.doc_types.map((t) => <Badge key={t}>{t}</Badge>)}
            </div>
          </div>
          <div className="w-full min-w-[180px] sm:w-56">
            <div className="mb-1.5 flex justify-between text-xs text-ink-2"><span>Settled fields</span><b className="text-ink">{settled} / {fields.length}</b></div>
            <div className="h-2 overflow-hidden rounded-full bg-mute-soft">
              <div className={cx("h-full rounded-full transition-all duration-500", settled === fields.length ? TONE_BAR.ok : TONE_BAR.brand)} style={{ width: `${(settled / fields.length) * 100}%` }} />
            </div>
          </div>
        </div>
        {data.triage.risk_flags.length > 0 && (
          <div className="mt-4"><Notice tone="warn" title="Risk flags">{data.triage.risk_flags.join(", ")}</Notice></div>
        )}
      </Card>

      <Tabs
        value={tab}
        onChange={setTab}
        tabs={[
          { id: "fields", label: <><ClipboardCheck size={16} /> Fields</>, count: data.triage.needs_attention },
          { id: "phone", label: <><PhoneCall size={16} /> Phone verification</> },
          { id: "categories", label: <><Layers size={16} /> Categories</> },
        ]}
      />

      {tab === "fields" && (
        <div className="anim-fade-up grid grid-cols-[minmax(0,1fr)] gap-3 xl:grid-cols-2">
          {fields.map((f) => <FieldCard key={f.key} f={f} busy={pending === f.key} onSave={save} meta={meta} />)}
        </div>
      )}
      {tab === "phone" && <PhonePanel id={id} meta={meta} onApplied={async () => { setData(await api.seller(id)); onChanged(); }} />}
      {tab === "categories" && <Categories data={data} />}
    </div>
  );
}

/* ------------------------------------------------------------------ */

function FieldCard({ f, busy, onSave, meta }: { f: TriageField; busy: boolean; onSave: (f: TriageField, v: string) => Promise<boolean>; meta: Meta | null }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(f.value ?? "");
  const b = BUCKET[f.bucket];
  const needsAction = f.bucket === "medium" || f.bucket === "low" || f.bucket === "missing";
  const alts = (f.material_conflict || f.suggested) ? f.alternatives.slice(0, 2) : [];
  const mono = f.key === "gstin" || f.key === "pincode";
  const edgeTone = { ok: "border-l-ok", warn: "border-l-warn", bad: "border-l-bad", info: "border-l-info", mute: "border-l-line-strong", brand: "border-l-brand" }[b.tone];

  const submit = async () => { if (draft.trim() && (await onSave(f, draft.trim()))) setEditing(false); };

  return (
    <Card className={cx("flex flex-col border-l-4 p-4", edgeTone)}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-xs font-medium uppercase tracking-wide text-ink-3">{f.label}</div>
          <div className={cx("mt-1 break-words text-lg font-semibold leading-snug", mono && f.value && "font-mono tracking-wide", !f.value && "text-base font-normal italic text-ink-3")}>
            {f.value ?? "Not found in the documents"}
          </div>
        </div>
        <Badge tone={b.tone} className="shrink-0">{b.label}</Badge>
      </div>

      {f.confidence != null && (
        <div className="mt-3"><Meter value={f.confidence} tone={confTone(f.confidence, meta?.thresholds.high, meta?.thresholds.medium)} label={`${f.label} confidence`} /></div>
      )}

      {f.reasons.length > 0 && (
        <ul className="mt-3 space-y-1 text-[13px] text-ink-2">
          {f.reasons.map((r, i) => (
            <li key={i} className="flex gap-2"><span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-ink-3" />{r}</li>
          ))}
        </ul>
      )}

      <div className="mt-auto pt-4">
        {editing ? (
          <div className="flex flex-wrap items-center gap-2">
            <input
              autoFocus
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") void submit(); if (e.key === "Escape") setEditing(false); }}
              aria-label={`New ${f.label}`}
              className={cx("h-10 min-w-0 flex-1 rounded-lg border border-line-strong bg-surface-2 px-3 text-sm outline-none focus:border-brand", mono && "font-mono")}
            />
            <Button variant="primary" loading={busy} icon={<Check size={16} />} onClick={() => void submit()} disabled={!draft.trim()}>Save</Button>
            <Button variant="ghost" icon={<X size={16} />} onClick={() => setEditing(false)}>Cancel</Button>
          </div>
        ) : (
          <div className="flex flex-wrap items-center gap-2">
            {needsAction && f.value && (
              <Button variant="primary" size="sm" loading={busy} icon={<Check size={15} />} onClick={() => void onSave(f, f.value!)}>Confirm</Button>
            )}
            {alts.map((a) => (
              <Button key={a} size="sm" disabled={busy} onClick={() => void onSave(f, a)} title={`Use ${a} instead`}>
                Use “{a.length > 22 ? a.slice(0, 22) + "…" : a}”
              </Button>
            ))}
            <Button
              variant={f.bucket === "missing" ? "primary" : "ghost"}
              size="sm"
              icon={<Pencil size={14} />}
              onClick={() => { setDraft(f.value ?? ""); setEditing(true); }}
            >
              {f.bucket === "missing" ? "Enter value" : "Edit"}
            </Button>
          </div>
        )}
      </div>
    </Card>
  );
}

function Categories({ data }: { data: SellerDetail }) {
  if (!data.categories.length) {
    return <Card><EmptyState icon={<Layers size={22} />} title="No category signal">No invoice products or NIC text were found in these documents.</EmptyState></Card>;
  }
  return (
    <Card className="anim-fade-up overflow-hidden">
      <div className="border-b border-line px-5 py-3 text-sm text-ink-2">Keyword-matched suggestions only. This is the weakest signal in the pipeline, so it is never auto-filled.</div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-surface-2 text-left text-xs uppercase tracking-wide text-ink-3">
            <tr><th className="px-5 py-2.5 font-medium">Category</th><th className="px-5 py-2.5 font-medium">Group</th><th className="px-5 py-2.5 text-right font-medium">Score</th></tr>
          </thead>
          <tbody>
            {data.categories.map((c) => (
              <tr key={c.category_name} className="border-t border-line">
                <td className="px-5 py-3 font-medium">{c.category_name}</td>
                <td className="px-5 py-3 text-ink-2">{c.group_name}</td>
                <td className="px-5 py-3 text-right tabular-nums">{c.confidence.toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
