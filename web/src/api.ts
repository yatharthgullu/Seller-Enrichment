// Typed client for the FastAPI backend (api/main.py).

export type Bucket = "high" | "medium" | "low" | "missing" | "verified";
export type FieldKey = "company_name" | "gstin" | "legal_status" | "city" | "state" | "pincode";

export interface Meta {
  thresholds: { high: number; medium: number };
  dataset_ready: boolean;
  sellers_in_dataset: number;
  has_samples: boolean;
  sarvam: { fetch_ready: boolean; missing: string[]; webhook_ready: boolean };
}

export interface SellerRow {
  id: string;
  docs: number;
  ready: boolean;
  needs_attention: number;
  risk_flags: string[];
  check: FieldKey[];
}

export interface EnrichSummary {
  loaded: boolean;
  sellers?: SellerRow[];
  stats?: { sellers: number; auto_pct: number; ready: number; needs_person: number };
  report?: { docs_read: number; skipped_type: number; skipped_json: number };
}

export interface TriageField {
  key: FieldKey;
  label: string;
  value: string | null;
  predicted_value: string | null;
  confidence: number | null;
  bucket: Bucket;
  action: string;
  reasons: string[];
  alternatives: string[];
  suggested: string | null;
  material_conflict: boolean;
  sources: string[];
}

export interface Category {
  category_name: string;
  group_name: string;
  confidence: number;
}

export interface SellerDetail {
  id: string;
  triage: { fields: TriageField[]; needs_attention: number; ready: boolean; risk_flags: string[] };
  doc_count: number;
  doc_types: string[];
  categories: Category[];
  corrections: Record<string, { old_value: string | null; new_value: string }>;
}

export interface CallSetup {
  plan: { confirm: FieldKey[]; collect: FieldKey[]; current: Record<string, string> };
  variables: Record<string, string>;
  csv: string;
}

export interface CallRow {
  key: FieldKey;
  field: string;
  asked: string;
  on_file: string;
  outcome: "confirmed" | "corrected" | "collected" | "not confirmed" | "not asked";
  value: string | null;
  check: string;
}

export interface CallView {
  attempt_id: string;
  glid: string;
  started: string | null;
  source: string;
  status: string;
  duration: number | null;
  failure_reason: string | null;
  disposition: string | null;
  summary: string | null;
  rows: CallRow[];
  applicable: number;
  applied: boolean;
  transcript: { role: string; en_text: string }[];
}

export interface SyncResult {
  fetched: number;
  connected: number;
  new: number;
  matched: number;
}

export interface Accuracy {
  loaded: boolean;
  sellers: number;
  headline: { key: string; label: string; rate: number; note: string }[];
  coverage: { rate: number; avg_fields: number; total_fields: number };
  category_top5: { rate: number; n: number };
  catalog: { sellers_with_catalog_gaps_and_invoice_products: number; products_price_fillable: number };
  threshold: {
    value: number;
    per_field: { key: string; label: string; rate: number }[];
    field_pass_rate: number;
    sellers_all_pass: number;
    sellers_need_review: number;
  };
}

export interface ExplorerField {
  value: string | null;
  confidence: number;
  raw_confidence: number;
  calibrated: boolean;
  sources: string[];
  candidates: Record<string, unknown>[];
}

export interface ExplorerSeller {
  id: string;
  doc_count: number;
  doc_types: string[];
  risk_flags: string[];
  fields: Record<FieldKey, ExplorerField>;
  raw_address: string | null;
  truth: Partial<Record<FieldKey | "partners" | "designation", string | null>>;
  categories: { category: string; group: string; confidence: number; real: boolean }[];
  products: Record<string, unknown>[];
}

export class ApiError extends Error {}

async function call<T>(url: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(url, init);
  } catch {
    throw new ApiError("Cannot reach the server. Is it running on port 8000?");
  }
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (body?.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* keep generic message */
    }
    throw new ApiError(detail);
  }
  return res.json() as Promise<T>;
}

const post = <T,>(url: string, body?: unknown) =>
  call<T>(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

export const api = {
  meta: () => call<Meta>("/api/meta"),
  enrich: () => call<EnrichSummary>("/api/enrich"),
  loadSample: () => post<EnrichSummary>("/api/enrich/sample"),
  upload: (files: File[]) => {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    return call<EnrichSummary>("/api/enrich/upload", { method: "POST", body: fd });
  },
  seller: (id: string) => call<SellerDetail>(`/api/enrich/sellers/${encodeURIComponent(id)}`),
  correct: (id: string, key: string, value: string) =>
    post<SellerDetail>(`/api/enrich/sellers/${encodeURIComponent(id)}/correct`, { key, value }),
  callSetup: (id: string, phone: string) =>
    call<CallSetup>(`/api/enrich/sellers/${encodeURIComponent(id)}/call?phone=${encodeURIComponent(phone)}`),
  calls: (glid: string) => call<{ calls: CallView[]; unmatched: number }>(`/api/calls?glid=${encodeURIComponent(glid)}`),
  syncCalls: (hours: number) => post<SyncResult>("/api/calls/sync", { hours }),
  applyCall: (attempt: string, glid: string) =>
    post<{ applied: string[] }>(`/api/calls/${encodeURIComponent(attempt)}/apply`, { glid }),
  accuracy: (threshold: number) => call<Accuracy>(`/api/accuracy?threshold=${threshold}`),
  explorerList: (q: string) =>
    call<{ total: number; sellers: { id: string; docs: number; flags: number }[] }>(
      `/api/explorer/sellers?q=${encodeURIComponent(q)}&limit=200`,
    ),
  explorerSeller: (id: string) => call<ExplorerSeller>(`/api/explorer/sellers/${encodeURIComponent(id)}`),
};
