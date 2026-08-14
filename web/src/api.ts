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
  confirmed: string;
  recovered: string;
};

export type ExceptionRow = {
  id: string;
  rule: string;
  status: string;
  title: string;
  amount_at_risk: string;
  currency: string;
  confidence: string;
  explanation?: Record<string, unknown>;
};

export type ExceptionDetail = ExceptionRow & {
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
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) {
    const detail = data?.detail;
    const msg = typeof detail === "string" ? detail : res.statusText;
    throw new ApiError(res.status, msg);
  }
  return data as T;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export const api = {
  me: () => req<Me>("/auth/me"),
  login: (email: string, password: string) =>
    req<Me>("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }),
  logout: () => req<{ ok: boolean }>("/auth/logout", { method: "POST" }),

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

  exceptions: (query: { status?: string; rule?: string } = {}) => {
    const q = new URLSearchParams();
    if (query.status) q.set("status", query.status);
    if (query.rule) q.set("rule", query.rule);
    const suffix = q.toString() ? `?${q}` : "";
    return req<MoneyBar & { count: number; exceptions: ExceptionRow[] }>(`/exceptions${suffix}`);
  },
  exception: (id: string) => req<ExceptionDetail>(`/exceptions/${id}`),
  transition: (
    id: string,
    body: { to_status: string; reason?: string; recovered_amount?: string; note?: string },
  ) => req<ExceptionRow>(`/exceptions/${id}/transition`, { method: "POST", body: JSON.stringify(body) }),

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
