import { useEffect, useRef, useState } from "react";
import {
  Check, CheckCircle2, ChevronDown, Clock, Copy, ExternalLink, FileSpreadsheet, MessageSquare, PhoneCall, RefreshCw,
} from "lucide-react";
import { api, type CallRow, type CallSetup, type CallView, type FieldKey, type Meta } from "../api";
import { Badge, Button, Card, Notice, Segmented, Skeleton, cx, download, useAsync, useToast, type Tone } from "../ui";

const LABEL: Record<FieldKey, string> = {
  company_name: "Company name", gstin: "GSTIN", legal_status: "Legal status", city: "City", state: "State", pincode: "Pincode",
};
const OUTCOME: Record<CallRow["outcome"], { tone: Tone; label: string }> = {
  confirmed: { tone: "ok", label: "Confirmed" },
  corrected: { tone: "warn", label: "Corrected" },
  collected: { tone: "brand", label: "Collected" },
  "not confirmed": { tone: "mute", label: "Not confirmed" },
  "not asked": { tone: "mute", label: "Not asked" },
};
const POLL_MS = 8000;

export default function PhonePanel({ id, meta, onApplied }: { id: string; meta: Meta | null; onApplied: () => void | Promise<void> }) {
  const toast = useToast();
  const setup = useAsync(() => api.callSetup(id, ""), [id]);
  const calls = useAsync(() => api.calls(id), [id]);
  const [hours, setHours] = useState(72);
  const [syncing, setSyncing] = useState(false);
  const [phone, setPhone] = useState("");
  const [applying, setApplying] = useState<string | null>(null);

  // Results that arrive by webhook show up on their own while this tab is open.
  const reloadRef = useRef(calls.reload);
  reloadRef.current = calls.reload;
  useEffect(() => {
    const t = setInterval(() => reloadRef.current(), POLL_MS);
    return () => clearInterval(t);
  }, []);

  const fetchReady = meta?.sarvam.fetch_ready ?? false;

  const sync = async () => {
    setSyncing(true);
    try {
      const r = await api.syncCalls(hours);
      calls.reload();
      toast(r.matched ? "ok" : "info", `Checked the last ${hours >= 24 ? `${hours / 24} day${hours > 24 ? "s" : ""}` : `${hours}h`}: ${r.connected} connected call${r.connected === 1 ? "" : "s"}, ${r.new} new.`);
    } catch (e) {
      toast("bad", (e as Error).message);
    } finally {
      setSyncing(false);
    }
  };

  const apply = async (c: CallView) => {
    setApplying(c.attempt_id);
    try {
      const r = await api.applyCall(c.attempt_id, id);
      toast("ok", `Applied ${r.applied.length} value${r.applied.length === 1 ? "" : "s"} to the profile`);
      calls.reload();
      await onApplied();
    } catch (e) {
      toast("bad", (e as Error).message);
    } finally {
      setApplying(null);
    }
  };

  return (
    <div className="anim-fade-up space-y-4">
      <Card className="divide-y divide-line">
        {/* 1 */}
        <Step n={1} title="Prepare the call" done={false}>
          {setup.loading && !setup.data ? <Skeleton className="h-24" /> : setup.data ? (
            <Prepare setup={setup.data} phone={phone} setPhone={setPhone} id={id} />
          ) : (
            <Notice tone="bad">{setup.error}</Notice>
          )}
        </Step>

        {/* 2 */}
        <Step n={2} title="Place the call in the Sarvam dashboard">
          <p className="text-sm text-ink-2">
            Open the agent <b className="text-ink">IndiaMART Seller Profile Verification</b>, start a call with the variables above, and make sure{" "}
            <code className="rounded bg-mute-soft px-1 font-mono text-[12px]">glid</code> is filled in. That is how the result finds its way back to this seller.
          </p>
          <a
            href="https://apps.sarvam.ai"
            target="_blank"
            rel="noreferrer"
            className="mt-3 inline-flex h-9 items-center gap-2 rounded-lg border border-line-strong bg-surface px-3 text-sm font-medium hover:bg-surface-2"
          >
            Open Sarvam dashboard <ExternalLink size={14} />
          </a>
        </Step>

        {/* 3 */}
        <Step n={3} title="Get the result">
          <div className="flex flex-wrap items-center gap-3">
            <Button variant="primary" loading={syncing} disabled={!fetchReady} icon={<RefreshCw size={16} />} onClick={() => void sync()}>
              Fetch latest calls
            </Button>
            <Segmented
              label="Look back"
              value={hours}
              onChange={setHours}
              options={[{ value: 6, label: "6h" }, { value: 24, label: "24h" }, { value: 72, label: "3 days" }, { value: 168, label: "7 days" }]}
            />
          </div>
          <p className="mt-3 flex items-center gap-2 text-xs text-ink-3">
            <span className={cx("h-2 w-2 rounded-full", meta?.sarvam.webhook_ready ? "bg-ok" : "bg-line-strong")} />
            {meta?.sarvam.webhook_ready
              ? "Webhook is set up: finished calls appear here automatically."
              : "No webhook configured: click Fetch after the call ends. This page also checks for new results every few seconds."}
          </p>
          {!fetchReady && meta && (
            <div className="mt-3"><Notice tone="warn" title="Sarvam is not connected">Add {meta.sarvam.missing.join(", ")} to the .env file and restart the server.</Notice></div>
          )}
        </Step>
      </Card>

      <div className="space-y-3">
        <h3 className="flex items-center gap-2 text-sm font-semibold">
          <PhoneCall size={16} className="text-ink-3" /> Calls for this seller
          {calls.data && calls.data.calls.length > 0 && <Badge>{calls.data.calls.length}</Badge>}
        </h3>
        {calls.loading && !calls.data && <Skeleton className="h-40" />}
        {calls.error && <Notice tone="bad">{calls.error}</Notice>}
        {calls.data && calls.data.calls.length === 0 && (
          <Card className="px-5 py-10 text-center text-sm text-ink-2">
            No call for GLID <b className="font-mono text-ink">{id}</b> yet. Once the call ends, it appears here.
          </Card>
        )}
        {calls.data?.calls.map((c) => <CallCard key={c.attempt_id} c={c} applying={applying === c.attempt_id} onApply={() => void apply(c)} />)}
        {!!calls.data?.unmatched && (
          <Notice tone="warn" title={`${calls.data.unmatched} stored call${calls.data.unmatched === 1 ? " has" : "s have"} no GLID`}>
            The <code className="font-mono">glid</code> variable was empty on those calls, so they cannot be matched to a seller. Run them again with the GLID filled in.
          </Notice>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */

function Step({ n, title, done, children }: { n: number; title: string; done?: boolean; children: React.ReactNode }) {
  return (
    <div className="flex gap-4 p-5">
      <div className={cx("grid h-7 w-7 shrink-0 place-items-center rounded-full text-xs font-bold", done ? "bg-ok text-white" : "bg-brand-soft text-brand")}>
        {done ? <Check size={14} /> : n}
      </div>
      <div className="min-w-0 flex-1">
        <h3 className="mb-2 text-sm font-semibold">{title}</h3>
        {children}
      </div>
    </div>
  );
}

function Prepare({ setup, phone, setPhone, id }: { setup: CallSetup; phone: string; setPhone: (v: string) => void; id: string }) {
  const toast = useToast();
  const { confirm, collect } = setup.plan;
  const [open, setOpen] = useState(false);

  if (!confirm.length && !collect.length) {
    return <Notice tone="ok" title="Nothing to confirm">Every field for this seller is already settled, so no call is needed.</Notice>;
  }

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(JSON.stringify(setup.variables, null, 2));
      toast("ok", "Variables copied. Paste them into the dashboard.");
    } catch {
      toast("bad", "Could not copy. Select the text in “Show variables” instead.");
    }
  };
  const csv = async () => {
    const r = await api.callSetup(id, phone).catch((e: Error) => { toast("bad", e.message); return null; });
    if (r) download(`cohort_${id}.csv`, r.csv);
  };

  const chips = (keys: FieldKey[], tone: Tone) => keys.map((k) => <Badge key={k} tone={tone}>{LABEL[k]}</Badge>);
  return (
    <div className="space-y-4">
      <dl className="grid grid-cols-[minmax(0,1fr)] gap-3 text-sm sm:grid-cols-2">
        <div>
          <dt className="mb-1.5 text-xs font-medium uppercase tracking-wide text-ink-3">Agent will read back and confirm</dt>
          <dd className="flex flex-wrap gap-1.5">{confirm.length ? chips(confirm, "warn") : <span className="text-ink-3">Nothing</span>}</dd>
        </div>
        <div>
          <dt className="mb-1.5 text-xs font-medium uppercase tracking-wide text-ink-3">Agent will ask for</dt>
          <dd className="flex flex-wrap gap-1.5">{collect.length ? chips(collect, "brand") : <span className="text-ink-3">Nothing</span>}</dd>
        </div>
      </dl>

      <div className="flex flex-wrap items-center gap-2">
        <Button icon={<Copy size={16} />} onClick={() => void copy()}>Copy variables</Button>
        <div className="flex flex-wrap items-center gap-2">
          <input
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            placeholder="+91… (for the CSV)"
            inputMode="tel"
            aria-label="Seller phone number for the cohort CSV"
            className="h-10 w-44 rounded-lg border border-line-strong bg-surface-2 px-3 text-sm outline-none focus:border-brand"
          />
          <Button icon={<FileSpreadsheet size={16} />} onClick={() => void csv()}>Cohort CSV</Button>
        </div>
        <Button variant="ghost" icon={<ChevronDown size={16} className={cx("transition", open && "rotate-180")} />} onClick={() => setOpen((o) => !o)} aria-expanded={open}>
          {open ? "Hide variables" : "Show variables"}
        </Button>
      </div>

      {open && (
        <div className="overflow-hidden rounded-lg border border-line">
          <table className="w-full text-[13px]">
            <tbody>
              {Object.entries(setup.variables).map(([k, v]) => (
                <tr key={k} className="border-b border-line last:border-0">
                  <td className="w-2/5 bg-surface-2 px-3 py-1.5 font-mono text-ink-2">{k}</td>
                  <td className="break-all px-3 py-1.5 font-mono">{v || <span className="text-ink-3">(empty)</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */

function CallCard({ c, applying, onApply }: { c: CallView; applying: boolean; onApply: () => void }) {
  const [showTranscript, setShowTranscript] = useState(false);
  const connected = c.status === "connected";
  const when = c.started ? new Date(c.started.endsWith("Z") || c.started.includes("+") ? c.started : c.started + "Z") : null;
  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={connected ? "ok" : "bad"}>{connected ? "Connected" : c.status}</Badge>
          {c.disposition && <Badge tone={c.disposition === "profile_confirmed" || c.disposition === "corrections_provided" ? "ok" : "warn"}>{c.disposition.replace(/_/g, " ")}</Badge>}
          <span className="flex items-center gap-1 text-xs text-ink-3">
            <Clock size={13} />
            {when ? when.toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) : "—"}
            {typeof c.duration === "number" && ` · ${Math.round(c.duration)}s`}
          </span>
        </div>
        <span className="text-xs text-ink-3">via {c.source}</span>
      </div>

      {!connected ? (
        <div className="p-5"><Notice tone="warn" title="This call did not connect">{c.failure_reason ?? c.status}. Nothing to apply.</Notice></div>
      ) : (
        <>
          {c.summary && <p className="px-5 pt-4 text-sm text-ink-2">{c.summary}</p>}
          <div className="overflow-x-auto px-5 py-4">
            <table className="w-full min-w-[560px] text-sm">
              <thead className="text-left text-xs uppercase tracking-wide text-ink-3">
                <tr>
                  <th className="pb-2 pr-3 font-medium">Field</th>
                  <th className="pb-2 pr-3 font-medium">Asked</th>
                  <th className="pb-2 pr-3 font-medium">On file</th>
                  <th className="pb-2 pr-3 font-medium">Outcome</th>
                  <th className="pb-2 font-medium">New value</th>
                </tr>
              </thead>
              <tbody>
                {c.rows.map((r) => {
                  const dim = r.outcome === "not asked";
                  const o = OUTCOME[r.outcome];
                  return (
                    <tr key={r.key} className={cx("border-t border-line align-top", dim && "opacity-50")}>
                      <td className="py-2.5 pr-3 font-medium">{r.field}</td>
                      <td className="py-2.5 pr-3 capitalize text-ink-2">{r.asked === "-" ? "—" : r.asked}</td>
                      <td className="py-2.5 pr-3 font-mono text-[13px] text-ink-2">{r.on_file || "—"}</td>
                      <td className="py-2.5 pr-3"><Badge tone={o.tone}>{o.label}</Badge></td>
                      <td className="py-2.5 font-mono text-[13px]">
                        {r.value ?? "—"}
                        {r.check.startsWith("rejected") && <div className="mt-0.5 font-sans text-xs text-bad">{r.check}</div>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line bg-surface-2 px-5 py-3">
            <Button variant="ghost" size="sm" icon={<MessageSquare size={15} />} onClick={() => setShowTranscript((s) => !s)} aria-expanded={showTranscript} disabled={!c.transcript.length}>
              {showTranscript ? "Hide transcript" : `Transcript (${c.transcript.length})`}
            </Button>
            {c.applied ? (
              <Badge tone="ok"><CheckCircle2 size={13} /> Applied to the profile</Badge>
            ) : c.applicable > 0 ? (
              <Button variant="primary" loading={applying} icon={<Check size={16} />} onClick={onApply}>
                Apply {c.applicable} value{c.applicable === 1 ? "" : "s"} to profile
              </Button>
            ) : (
              <span className="text-sm text-ink-3">Nothing was confirmed, so there is nothing to apply.</span>
            )}
          </div>

          {showTranscript && (
            <div className="scroll-thin max-h-80 space-y-2 overflow-y-auto border-t border-line px-5 py-4">
              {c.transcript.map((t, i) => (
                <div key={i} className={cx("flex", t.role === "agent" ? "justify-start" : "justify-end")}>
                  <div className={cx("max-w-[85%] rounded-2xl px-3.5 py-2 text-sm", t.role === "agent" ? "rounded-bl-sm bg-mute-soft" : "rounded-br-sm bg-brand-soft text-ink")}>
                    <div className="mb-0.5 text-[11px] font-semibold uppercase tracking-wide text-ink-3">{t.role === "agent" ? "Agent" : "Seller"}</div>
                    {t.en_text}
                  </div>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </Card>
  );
}
