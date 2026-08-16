import { useState } from "react";
import { api, type FileUploadResult, type IntakePreview } from "./api";

const KIND_LABEL: Record<string, string> = {
  invoice_pdf: "Supplier invoice",
  document_pdf: "PDF document",
  books_export: "Books / ledger (Zoho)",
  bank_statement: "Bank statement",
  bank_pdf: "Bank statement PDF",
  gstr2b: "GSTR-2B (GST portal)",
  training_pack: "Training file",
  workpaper: "Not a supplier invoice",
  tabular: "Spreadsheet",
  zip: "Zip of mixed files",
  unknown: "Unrecognised",
};

const SLOTS = [
  { id: "vendor", label: "1. Vendors", hint: "Name and code / GSTIN if you have it", need: true },
  { id: "invoice", label: "2. Invoices", hint: "Invoice number, date, amount", need: true },
  { id: "payment", label: "3. Payments", hint: "Date, amount, which invoice", need: true },
  { id: "credit_note", label: "Credit notes (optional)", hint: "Only if you have them", need: false },
] as const;

const FIELD_OPTIONS: { id: string; label: string }[] = [
  { id: "", label: "— ignore this column —" },
  { id: "vendor.name", label: "Vendor name" },
  { id: "vendor.source_ref", label: "Vendor code" },
  { id: "vendor.tax_id", label: "GSTIN / tax id" },
  { id: "vendor.registration_id", label: "PAN / registration" },
  { id: "invoice.invoice_number", label: "Invoice number" },
  { id: "invoice.invoice_date", label: "Invoice date" },
  { id: "invoice.gross_amount", label: "Invoice amount" },
  { id: "invoice.source_ref", label: "Invoice id" },
  { id: "invoice.currency", label: "Currency" },
  { id: "payment.amount", label: "Payment amount" },
  { id: "payment.payment_date", label: "Payment date" },
  { id: "payment.invoice_ref", label: "Paid against invoice" },
  { id: "payment.account", label: "Bank account paid to" },
  { id: "payment.source_ref", label: "Payment id" },
  { id: "payment.reference", label: "UTR / cheque / ref" },
  { id: "credit_note.amount", label: "Credit amount" },
  { id: "credit_note.note_date", label: "Credit date" },
  { id: "credit_note.source_ref", label: "Credit note id" },
];

export function ImportDesk({ onRan }: { onRan: (runId: string) => void }) {
  const [batchId, setBatchId] = useState<string | null>(null);
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

  const [intake, setIntake] = useState<IntakePreview | null>(null);

  const have = new Set(files.map((f) => f.entity));
  const ready = ["vendor", "invoice", "payment"].every((id) => have.has(id));
  const skipped = intake?.files.filter((f) => f.skip) ?? [];

  return (
    <div className="main">
      <section className="panel">
        <h2>1. Drop whatever you have</h2>
        <div className="guide">
          <h3>First time here?</h3>
          <ol>
            <li>Drop a zip, invoice PDFs, a bank statement, a GSTR-2B, or a Zoho “Account Transactions” PDF.</li>
            <li>Pulse reads the files and shows what it understood. It does not book anything.</li>
            <li>
              Press <strong>Review findings</strong>. Each row on the next screen is a question for you —
              confirm if it is real, dismiss if it is not.
            </li>
          </ol>
          <p>A finding is a question, not a booked entry, and not money already saved.</p>
        </div>
        <label className="btn file-btn">
          Choose files
          <input
            type="file"
            multiple
            hidden
            disabled={busy}
            onChange={async (ev) => {
              const list = ev.target.files ? Array.from(ev.target.files) : [];
              ev.target.value = "";
              if (!list.length) return;
              setBusy(true);
              setErr(null);
              try {
                const preview = await api.dropAnything(list);
                setIntake(preview);
                setMsg(`Read ${list.length} file(s). Check the list, then press Review findings.`);
              } catch (ex) {
                setErr(ex instanceof Error ? ex.message : "Could not read those files");
              } finally {
                setBusy(false);
              }
            }}
          />
        </label>
        {intake && (
          <div style={{ marginTop: "1rem" }}>
            <p>
              <strong>
                {intake.mode === "zero_books"
                  ? "Reconstructing from documents"
                  : intake.mode === "proper_books"
                    ? "Reading exported books"
                    : intake.mode === "mixed"
                      ? "Documents + books"
                      : intake.mode.replaceAll("_", " ")}
              </strong>{" "}
              — {intake.summary}
            </p>
            <p className="hint">
              {intake.invoices.length} bills
              {intake.ledger_invoices ? ` (${intake.ledger_invoices} from the ledger)` : ""} ·{" "}
              {intake.bank_out} bank payments
              {intake.ledger_payments ? ` · ${intake.ledger_payments} ledger payments` : ""} ·{" "}
              {intake.two_b} GST portal rows
              {intake.needs_human_invoices
                ? ` · ${intake.needs_human_invoices} bills still need a closer look`
                : ""}
            </p>
            <table>
              <thead>
                <tr>
                  <th>File</th>
                  <th>Pulse read it as</th>
                </tr>
              </thead>
              <tbody>
                {intake.files.map((f) => (
                  <tr key={f.filename}>
                    <td>{f.filename}</td>
                    <td className="kind">
                      {KIND_LABEL[f.kind] ?? f.kind.replaceAll("_", " ")}
                      {f.skip ? (
                        <span className="skip"> — not an invoice. {f.reason}</span>
                      ) : f.reason ? (
                        ` — ${f.reason}`
                      ) : (
                        ""
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {skipped.length > 0 && (
              <div className="guide skip-box">
                <h3>Not treated as invoices — would become fake bills</h3>
                <p>
                  Pulse left these out on purpose. They are ITR papers, profiles, or training files.
                  If they were booked as supplier invoices, the desk would show money that is not a
                  payable.
                </p>
                <ul>
                  {skipped.map((f) => (
                    <li key={f.filename}>
                      <strong>{f.filename}</strong> — {f.reason}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {intake.limitations.length > 0 && (
              <ul className="hint">
                {intake.limitations.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            )}
            <button
              className="btn"
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                setErr(null);
                try {
                  const res = await api.commitIntake(intake.batch_id);
                  onRan(res.run_id);
                } catch (ex) {
                  setErr(ex instanceof Error ? ex.message : "Could not run");
                } finally {
                  setBusy(false);
                }
              }}
            >
              {busy ? "Working…" : "Review findings →"}
            </button>
            {err && <p className="err">{err}</p>}
          </div>
        )}
      </section>

      <section className="panel">
        <h2>Or map three books files</h2>
        <p className="hint" style={{ marginTop: 0 }}>
          Three files. We guess the columns; you only fix a wrong guess. If a date looks like
          03/07/2026, say whether the day comes first.
        </p>
        <label className="inline">
          How dates are written
          <select value={dateFormat} onChange={(e) => setDateFormat(e.target.value)}>
            <option value="ymd">2025-06-02 (year first)</option>
            <option value="dmy">02/06/2025 (India — day first)</option>
            <option value="mdy">06/02/2025 (month first)</option>
          </select>
        </label>
      </section>

      {SLOTS.map((slot) => {
        const uploaded = files.find((f) => f.entity === slot.id);
        return (
          <section className="panel" key={slot.id}>
            <div className="slot-head">
              <div>
                <h2>{slot.label}</h2>
                <p className="hint" style={{ margin: 0 }}>
                  {slot.hint}
                  {uploaded ? ` · ${uploaded.row_count} rows from ${uploaded.filename}` : ""}
                </p>
              </div>
              <label className="btn btn-ghost file-btn">
                {uploaded ? "Replace file" : "Choose file"}
                <input
                  type="file"
                  accept=".csv,.xlsx,.xls"
                  hidden
                  disabled={busy}
                  onChange={async (ev) => {
                    const file = ev.target.files?.[0];
                    ev.target.value = "";
                    if (!file) return;
                    setBusy(true);
                    setErr(null);
                    try {
                      const id = await ensureBatch();
                      const uploadedFile = await api.uploadFile(id, slot.id, file);
                      if (uploadedFile.missing.length === 0) {
                        await api.mapFile(id, uploadedFile.id, uploadedFile.mapping, dateFormat);
                      }
                      setFiles((prev) => [
                        ...prev.filter((f) => f.entity !== uploadedFile.entity),
                        uploadedFile,
                      ]);
                      setMsg(`${file.name} loaded.`);
                    } catch (ex) {
                      setErr(ex instanceof Error ? ex.message : "Upload failed");
                    } finally {
                      setBusy(false);
                    }
                  }}
                />
              </label>
            </div>
            {uploaded && uploaded.missing.length > 0 && (
              <p className="err">This file still needs: {uploaded.missing.join(", ")}</p>
            )}
            {uploaded && (
              <table>
                <thead>
                  <tr>
                    <th>Column in your file</th>
                    <th>Means</th>
                  </tr>
                </thead>
                <tbody>
                  {uploaded.headers.map((h) => (
                    <tr key={h}>
                      <td>{h}</td>
                      <td>
                        <select
                          className="field"
                          value={uploaded.mapping[h] ?? ""}
                          onChange={(e) => {
                            const value = e.target.value;
                            setFiles((prev) =>
                              prev.map((row) =>
                                row.id === uploaded.id
                                  ? { ...row, mapping: { ...row.mapping, [h]: value } }
                                  : row,
                              ),
                            );
                          }}
                        >
                          {!FIELD_OPTIONS.some((o) => o.id === (uploaded.mapping[h] ?? "")) && (
                            <option value={uploaded.mapping[h]}>{uploaded.mapping[h]}</option>
                          )}
                          {FIELD_OPTIONS.map((o) => (
                            <option key={o.id || "none"} value={o.id}>
                              {o.label}
                            </option>
                          ))}
                        </select>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
        );
      })}

      <section className="panel">
        <h2>Find issues</h2>
        <p className="hint" style={{ marginTop: 0 }}>
          Loads the three lists, then runs the payment rules. You will land on Findings.
        </p>
        {err && <p className="err">{err}</p>}
        {msg && <p className="ok-msg">{msg}</p>}
        <button
          className="btn"
          disabled={!ready || busy}
          onClick={async () => {
            if (!batchId) return;
            setBusy(true);
            setErr(null);
            try {
              for (const f of files) {
                const mapping = Object.fromEntries(
                  Object.entries(f.mapping).filter(([, value]) => Boolean(value)),
                );
                const mapped = await api.mapFile(batchId, f.id, mapping, dateFormat);
                if (!mapped.ok) {
                  setErr(`${f.filename} has ${mapped.errors.length} problem(s). Fix the mapping.`);
                  return;
                }
              }
              const res = await api.commitImport(batchId);
              if (!res.ok) {
                setErr("The files loaded, but some rows failed checks. Fix dates or amounts and try again.");
                return;
              }
              const run = await api.run(batchId);
              onRan(run.id);
            } catch (ex) {
              setErr(ex instanceof Error ? ex.message : "Could not run");
            } finally {
              setBusy(false);
            }
          }}
        >
          {busy ? "Working…" : ready ? "Find issues" : "Add vendors, invoices and payments first"}
        </button>
      </section>
    </div>
  );
}
