import { useState } from "react";
import { api, type FileUploadResult } from "./api";

const ENTITIES = [
  { id: "vendor", label: "Vendors" },
  { id: "invoice", label: "Invoices" },
  { id: "payment", label: "Payments" },
  { id: "credit_note", label: "Credit notes" },
] as const;

export function ImportDesk({ onRan }: { onRan: (runId: string) => void }) {
  const [batchId, setBatchId] = useState<string | null>(null);
  const [entity, setEntity] = useState<string>("payment");
  const [dateFormat, setDateFormat] = useState("ymd");
  const [files, setFiles] = useState<FileUploadResult[]>([]);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function ensureBatch() {
    if (batchId) return batchId;
    const created = await api.createImport();
    setBatchId(created.id);
    return created.id;
  }

  return (
    <div className="main">
      <section className="panel">
        <h2>1. Load the books</h2>
        <p className="hint" style={{ marginTop: 0 }}>
          CSV or Excel. One file per list. Map columns, then commit. Dates that look like 03/07/2026
          need you to say day-first (India) or month-first. We will not guess.
        </p>
        <div className="drop">
          <select value={entity} onChange={(e) => setEntity(e.target.value)}>
            {ENTITIES.map((e) => (
              <option key={e.id} value={e.id}>
                {e.label}
              </option>
            ))}
          </select>
          <input
            type="file"
            accept=".csv,.xlsx,.xls"
            onChange={async (ev) => {
              const file = ev.target.files?.[0];
              ev.target.value = "";
              if (!file) return;
              setBusy(true);
              setErr(null);
              try {
                const id = await ensureBatch();
                const uploaded = await api.uploadFile(id, entity, file);
                setFiles((prev) => [...prev.filter((f) => f.entity !== uploaded.entity), uploaded]);
              } catch (ex) {
                setErr(ex instanceof Error ? ex.message : "Upload failed");
              } finally {
                setBusy(false);
              }
            }}
          />
          <label>
            Date format{" "}
            <select value={dateFormat} onChange={(e) => setDateFormat(e.target.value)}>
              <option value="ymd">yyyy-mm-dd</option>
              <option value="dmy">dd/mm/yyyy (India)</option>
              <option value="mdy">mm/dd/yyyy</option>
            </select>
          </label>
        </div>
        {err && <p className="err">{err}</p>}
        {msg && <p className="hint">{msg}</p>}
      </section>

      {files.map((f) => (
        <section className="panel" key={f.id}>
          <h2>
            {f.filename} · {f.entity} · {f.row_count} rows
          </h2>
          {f.missing.length > 0 && (
            <p className="err">Still need: {f.missing.join(", ")}</p>
          )}
          <table>
            <thead>
              <tr>
                <th>Column in file</th>
                <th>Maps to</th>
              </tr>
            </thead>
            <tbody>
              {f.headers.map((h) => (
                <tr key={h}>
                  <td>{h}</td>
                  <td>
                    <input
                      className="field"
                      value={f.mapping[h] ?? ""}
                      onChange={(e) => {
                        const value = e.target.value;
                        setFiles((prev) =>
                          prev.map((row) =>
                            row.id === f.id
                              ? { ...row, mapping: { ...row.mapping, [h]: value } }
                              : row,
                          ),
                        );
                      }}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="btn-row" style={{ marginTop: "0.75rem" }}>
            <button
              className="btn btn-ghost"
              disabled={busy}
              onClick={async () => {
                if (!batchId) return;
                setBusy(true);
                setErr(null);
                try {
                  const res = await api.mapFile(batchId, f.id, f.mapping, dateFormat);
                  setMsg(
                    res.ok
                      ? `${f.filename} mapped.`
                      : `${res.errors.length} validation issue(s) — fix the file or mapping.`,
                  );
                } catch (ex) {
                  setErr(ex instanceof Error ? ex.message : "Map failed");
                } finally {
                  setBusy(false);
                }
              }}
            >
              Confirm mapping
            </button>
          </div>
        </section>
      ))}

      <section className="panel">
        <h2>2. Commit and run</h2>
        <div className="btn-row">
          <button
            className="btn btn-ghost"
            disabled={!batchId || busy}
            onClick={async () => {
              if (!batchId) return;
              setBusy(true);
              setErr(null);
              try {
                const res = await api.commitImport(batchId);
                setMsg(res.ok ? `Loaded ${JSON.stringify(res.counts)}` : "Commit failed — see errors.");
                if (!res.ok) setErr("Validation failed on commit.");
              } catch (ex) {
                setErr(ex instanceof Error ? ex.message : "Commit failed");
              } finally {
                setBusy(false);
              }
            }}
          >
            Commit import
          </button>
          <button
            className="btn"
            disabled={!batchId || busy}
            onClick={async () => {
              if (!batchId) return;
              setBusy(true);
              setErr(null);
              try {
                const run = await api.run(batchId);
                setMsg(`Run ${run.id} ${run.status}`);
                onRan(run.id);
              } catch (ex) {
                setErr(ex instanceof Error ? ex.message : "Run failed");
              } finally {
                setBusy(false);
              }
            }}
          >
            Run rules
          </button>
        </div>
      </section>
    </div>
  );
}
