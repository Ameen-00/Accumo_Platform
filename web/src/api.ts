/** Pulse API. Session cookie is httpOnly — always send credentials. */

export type Me = {
  id: string;
  email: string;
  name: string;
  role: string;
  organisation_id: string | null;
};

export type MoneyBar = {
  identified: string;
  completeness: string;
  to_confirm: string;
  confirmed: string;
  recovered: string;
  queues?: { integrity: number; completeness: number; match: number; all: number };
};

export type ExceptionRow = {
  id: string;
  rule: string;
  family?: string;
  status: string;
  title: string;
  amount_at_risk: string;
  currency: string;
  confidence: string;
  explanation?: Record<string, unknown>;
  next_action?: string;
};

export type IntakePreview = {
  batch_id: string;
  mode: string;
  summary: string;
  limitations: string[];
  counts: Record<string, number>;
  files: { filename: string; kind: string; reason: string; skip: boolean }[];
  invoices: { invoice_number: string; amount: string; vendor_name: string; needs_human: boolean; missing: string[] }[];
  bank_out: number;
  bank_in: number;
  two_b: number;
  ledger?: number;
  ledger_invoices?: number;
  ledger_payments?: number;
  needs_human_invoices: number;
  skipped: string[];
  errors: string[];
};

export type ExceptionDetail = ExceptionRow & {
  brain?: string | null;
  evidence: Record<string, unknown>;
  events: {
    from: string | null;
    to: string;
    reason: string | null;
    recovered_amount: string | null;
    note: string | null;
    at: string | null;
  }[];
};

export type FileUploadResult = {
  id: string;
  entity: string;
  filename: string;
  headers: string[];
  row_count: number;
  suggested_mapping: Record<string, string>;
  mapping: Record<string, string>;
  preview: Record<string, string>[];
  needs_date_format: boolean;
  missing: string[];
};

async function req<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetch(path, { ...init, headers, credentials: "include" });
  if (res.status === 401) {
    throw new ApiError(401, "Not signed in");
  }
  const text = await res.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      if (!res.ok) {
        throw new ApiError(res.status, "Pulse could not finish that step. Press Review findings again.");
      }
      throw new ApiError(res.status, "The server sent a broken reply.");
    }
  }
  if (!res.ok) {
    throw new ApiError(res.status, explainError(data, res.statusText || "Request failed"));
  }
  return data as T;
}

function explainError(data: unknown, fallback: string): string {
  const detail = data && typeof data === "object" ? (data as { detail?: unknown }).detail : undefined;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail) && detail.length) {
    const first = detail[0] as { msg?: string };
    if (first?.msg) return first.msg;
  }
  return fallback;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export type RunDesk = {
  id: string;
  status: string;
  stats: {
    mode?: string;
    summary?: string;
    limitations?: string[];
    invoices?: number;
    payments?: number;
    two_b?: number;
    suggested?: number;
    dup_docs?: number;
    invoices_on_2b?: number;
    open_invoices?: number;
    two_b_gaps?: number;
    credits?: number;
    bank_files?: number;
    ledger?: number;
    ledger_invoices?: number;
    ledger_payments?: number;
    briefing?: { start: string; spoken?: string; steps: string[]; guardrail: string; voice?: string | null };
    findings?: number;
    created?: number;
  };
};

export const api = {
  me: () => req<Me>("/auth/me"),
  getRun: (id: string) => req<RunDesk>(`/runs/${id}`),
  latestRun: () => req<RunDesk>("/runs/latest"),
  login: (email: string, password: string) =>
    req<Me>("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }),
  logout: () => req<{ ok: boolean }>("/auth/logout", { method: "POST" }),

  dropAnything: async (fileList: File[]) => {
    const body = new FormData();
    for (const file of fileList) body.append("files", file);
    return req<IntakePreview>("/intake/drop", { method: "POST", body });
  },
  commitIntake: (batchId: string) =>
    req<{
      ok: boolean;
      batch_id: string;
      run_id: string;
      counts: Record<string, number>;
      mode: string;
      limitations: string[];
      stats: Record<string, unknown>;
    }>(`/intake/${batchId}/commit-and-run`, { method: "POST" }),

  createImport: () => req<{ id: string; status: string }>("/imports", { method: "POST" }),
  getImport: (id: string) =>
    req<{
      id: string;
      status: string;
      date_format: string | null;
      row_counts: Record<string, number> | null;
      files: { id: string; entity: string; filename: string; row_count: number; mapping: Record<string, string> }[];
    }>(`/imports/${id}`),
  uploadFile: async (batchId: string, entity: string, file: File) => {
    const body = new FormData();
    body.append("entity", entity);
    body.append("file", file);
    return req<FileUploadResult>(`/imports/${batchId}/files`, { method: "POST", body });
  },
  mapFile: (
    batchId: string,
    fileId: string,
    mapping: Record<string, string>,
    date_format: string | null,
  ) =>
    req<{ ok: boolean; errors: { row?: number; message?: string }[]; needs_date_format: boolean }>(
      `/imports/${batchId}/files/${fileId}/map`,
      { method: "PUT", body: JSON.stringify({ mapping, date_format }) },
    ),
  commitImport: (batchId: string) =>
    req<{ ok: boolean; counts?: Record<string, number>; errors?: unknown[] }>(`/imports/${batchId}/commit`, {
      method: "POST",
    }),

  run: (batchId: string) =>
    req<{ id: string; status: string; stats: Record<string, unknown> }>("/runs", {
      method: "POST",
      body: JSON.stringify({ batch_id: batchId }),
    }),

  exceptions: (query: { status?: string; rule?: string; family?: string } = {}) => {
    const q = new URLSearchParams();
    if (query.status) q.set("status", query.status);
    if (query.rule) q.set("rule", query.rule);
    if (query.family) q.set("family", query.family);
    const suffix = q.toString() ? `?${q}` : "";
    return req<MoneyBar & { count: number; exceptions: ExceptionRow[] }>(`/exceptions${suffix}`);
  },
  exception: (id: string) => req<ExceptionDetail>(`/exceptions/${id}`),
  transition: (
    id: string,
    body: { to_status: string; reason?: string; recovered_amount?: string; note?: string },
  ) => req<ExceptionRow>(`/exceptions/${id}/transition`, { method: "POST", body: JSON.stringify(body) }),
  bulkTransition: (
    body: { ids: string[]; to_status: string; reason?: string; recovered_amount?: string; note?: string },
  ) => req<{ ok: boolean; moved: string[] }>("/exceptions/bulk-transition", { method: "POST", body: JSON.stringify(body) }),

  pendingIdentities: () =>
    req<{ pending: { id: string; canonical_name: string; members: { name: string }[] }[] }>("/identities/pending"),

  makePack: (runId: string) =>
    req<{ id: string; status: string; filename: string; sha256: string }>("/reports/evidence-pack", {
      method: "POST",
      body: JSON.stringify({ run_id: runId }),
    }),
  downloadPack: async (reportId: string, filename: string) => {
    const res = await fetch(`/reports/${reportId}/download`, { credentials: "include" });
    if (!res.ok) throw new ApiError(res.status, "Download failed");
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  },
};
