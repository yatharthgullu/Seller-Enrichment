import { useEffect, useRef, useState } from "react";
import { Database, FileArchive, FileJson, FileSpreadsheet, FileText, X } from "lucide-react";
import { api } from "../api";
import { Badge, Button, Skeleton, cx, useAsync } from "../ui";
import { LinkButton } from "./shared";

const COLUMNS: [string, string][] = [
  ["fk_glusr_usr_id", "The seller's GLID. Rows with the same GLID are fused into one profile. (seller_id also works.)"],
  ["document_type", "One of the four types below. Case-sensitive; anything else is skipped and counted. (doc_type also works.)"],
  ["llm_extraction", "What the upstream OCR / LLM step extracted from that one document, as a JSON object."],
];

const DOC_TYPES: [string, string, string][] = [
  ["Product Invoice", "CompanyName[], GST[], Address[], Products[]", "company, GSTIN, address, products"],
  ["Sign Board", "CompanyName[], GST[], Address[]", "company, GSTIN, address"],
  ["Udhyam Certificate", "udyam_data (trade name, official address, enterprise type), gstin_verification", "company, GSTIN, address, risk flag"],
  ["CANCELLED CHEQUE", "accholder_name.value, bank_address.value", "company (weak), locality (very weak)"],
];

const EXAMPLE = `fk_glusr_usr_id,document_type,llm_extraction
900100005,Product Invoice,"{""CompanyName"":[""VELAN ELECTRICALS""],
  ""GST"":[""33DNRPV8842H1Z6""],""Address"":[""No. 7, Gandhi Road""]}"
900100005,Sign Board,"{""CompanyName"":[""VELAN ELECTRICALS""]}"`;

/** A "Data format" button that opens a dialog: downloads, the input structure, and the 10 test scenarios. */
export function SampleDataButton({ hasPack }: { hasPack: boolean }) {
  const ref = useRef<HTMLDialogElement>(null);
  const [opened, setOpened] = useState(false);
  // deep link: #/enrich?dialog=data opens it straight away
  useEffect(() => {
    if (new URLSearchParams(window.location.hash.split("?")[1] ?? "").get("dialog") === "data") {
      setOpened(true);
      ref.current?.showModal();
    }
  }, []);
  return (
    <>
      <Button icon={<Database size={16} />} onClick={() => { setOpened(true); ref.current?.showModal(); }}>Data format</Button>
      <dialog
        ref={ref}
        onClick={(e) => { if (e.target === ref.current) ref.current?.close(); }}
        className="m-auto w-[min(960px,calc(100vw-1.5rem))] max-h-[calc(100vh-2rem)] rounded-2xl border border-line bg-surface p-0 text-ink shadow-pop backdrop:bg-black/50"
        aria-labelledby="sd-title"
      >
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-line bg-surface px-5 py-4 sm:px-6">
          <div>
            <h2 id="sd-title" className="text-lg font-semibold">What we pass in</h2>
            <p className="text-sm text-ink-2">The input structure, plus a 10-seller test pack that covers every outcome.</p>
          </div>
          <button onClick={() => ref.current?.close()} aria-label="Close" className="grid h-9 w-9 place-items-center rounded-lg text-ink-2 hover:bg-mute-soft hover:text-ink">
            <X size={18} />
          </button>
        </div>
        {opened && <Body hasPack={hasPack} />}
      </dialog>
    </>
  );
}

function Body({ hasPack }: { hasPack: boolean }) {
  const { data, loading } = useAsync(api.scenarios, []);
  return (
    <div className="space-y-7 px-5 py-5 sm:px-6">
      {hasPack && (
        <section>
          <h3 className="mb-3 text-sm font-semibold">Download the test pack</h3>
          <div className="flex flex-wrap gap-2">
            <LinkButton href="/api/enrich/samples/seller_enrichment_test_pack.zip" icon={<FileArchive size={16} />} className="border-brand bg-brand-soft text-brand">All files (.zip)</LinkButton>
            <LinkButton href="/api/enrich/samples/sample_10_sellers.csv" icon={<FileSpreadsheet size={16} />}>Upload file (CSV)</LinkButton>
            <LinkButton href="/api/enrich/samples/sample_10_sellers.json" icon={<FileJson size={16} />}>Same data (JSON)</LinkButton>
            <LinkButton href="/api/enrich/samples/sample_10_sellers_scenarios.csv" icon={<FileSpreadsheet size={16} />}>Scenarios (CSV)</LinkButton>
            <LinkButton href="/api/enrich/samples/README.md" icon={<FileText size={16} />}>Guide (.md)</LinkButton>
          </div>
        </section>
      )}

      <section>
        <h3 className="mb-1 text-sm font-semibold">Input: one row per KYC document</h3>
        <p className="mb-3 text-sm text-ink-2">
          The app does not read images. It fuses the fields an upstream OCR / LLM step has already extracted, across all of a seller's documents.
        </p>
        <Table head={["Column", "Meaning"]} rows={COLUMNS.map(([a, b]) => [<code key={a} className="font-mono text-[13px]">{a}</code>, b])} />
        <pre className="scroll-thin mt-3 overflow-x-auto rounded-lg bg-surface-2 p-3 font-mono text-[12px] leading-relaxed text-ink-2">{EXAMPLE}</pre>
      </section>

      <section>
        <h3 className="mb-3 text-sm font-semibold">What is read from each document type</h3>
        <Table
          head={["document_type", "Keys read from llm_extraction", "Feeds"]}
          rows={DOC_TYPES.map(([a, b, c]) => [<code key={a} className="font-mono text-[13px]">{a}</code>, b, c])}
        />
        <p className="mt-3 text-sm text-ink-2">
          <b className="text-ink">Legal status is derived, not read:</b> it comes from the GSTIN's PAN entity character, so it is only as certain as the GSTIN.
          Missing keys are fine; a field nothing supplies comes back as <i>fill in</i>.
        </p>
      </section>

      <section>
        <h3 className="mb-1 flex items-center gap-2 text-sm font-semibold">The 10 test sellers <Badge tone="brand">fictional</Badge></h3>
        <p className="mb-3 text-sm text-ink-2">Each seller is designed to land somewhere different in the triage. Confirm means the agent reads a value back; collect means it asks for it.</p>
        {loading && <Skeleton className="h-64" />}
        {data && (
          <Table
            head={["GLID", "Scenario", "Will confirm", "Will collect"]}
            rows={data.scenarios.map((s) => [
              <span key="g" className="font-mono text-[13px]">{s.glid}</span>,
              <div key="s"><div className="font-medium">{s.scenario}</div><div className="mt-0.5 text-xs text-ink-3">{s.what_to_look_for}</div></div>,
              <Fields key="c" v={s.expected_to_confirm} tone="warn" />,
              <Fields key="k" v={s.expected_to_collect} tone="brand" />,
            ])}
          />
        )}
      </section>
    </div>
  );
}

function Fields({ v, tone }: { v: string; tone: "warn" | "brand" }) {
  if (!v || v === "-") return <span className="text-ink-3">—</span>;
  return <div className="flex flex-wrap gap-1">{v.split(",").map((f) => <Badge key={f} tone={tone}>{f.trim().replace(/_/g, " ")}</Badge>)}</div>;
}

function Table({ head, rows }: { head: string[]; rows: React.ReactNode[][] }) {
  return (
    <div className="scroll-thin overflow-x-auto rounded-xl border border-line">
      <table className="w-full min-w-[560px] text-sm">
        <thead className="bg-surface-2 text-left text-xs uppercase tracking-wide text-ink-3">
          <tr>{head.map((h) => <th key={h} className="px-4 py-2.5 font-medium">{h}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className={cx("border-t border-line align-top")}>
              {r.map((c, j) => <td key={j} className="px-4 py-2.5 text-ink-2 first:text-ink">{c}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
