import { useCallback, useEffect, useState } from "react";
import { api, type ExceptionDetail, type ExceptionRow, type MoneyBar } from "./api";

function money(currency: string, amount: string) {
  const n = Number(amount);
  if (Number.isNaN(n)) return `${currency} ${amount}`;
  return `${currency} ${n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function Findings({ runId }: { runId: string | null }) {
  const [bar, setBar] = useState<MoneyBar>({ identified: "0", confirmed: "0", recovered: "0" });
  const [rows, setRows] = useState<ExceptionRow[]>([]);
  const [filter, setFilter] = useState("");
  const [sel, setSel] = useState(0);
  const [open, setOpen] = useState<ExceptionDetail | null>(null);
  const [reason, setReason] = useState("");
  const [recovered, setRecovered] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [packMsg, setPackMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    const data = await api.exceptions(filter ? { status: filter } : {});
    setBar({ identified: data.identified, confirmed: data.confirmed, recovered: data.recovered });
    setRows(data.exceptions);
    setSel((i) => Math.min(i, Math.max(0, data.exceptions.length - 1)));
  }, [filter]);

  useEffect(() => {
    load().catch((ex) => setErr(ex instanceof Error ? ex.message : "Could not load findings"));
  }, [load]);

  const current = rows[sel];

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if (e.key === "j") setSel((i) => Math.min(rows.length - 1, i + 1));
      if (e.key === "k") setSel((i) => Math.max(0, i - 1));
      if (e.key === "Enter" && current) void openRow(current.id);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [rows, current]);

  async function openRow(id: string) {
    setErr(null);
    setOpen(await api.exception(id));
  }

  async function move(to: string) {
    if (!current) return;
    setBusy(true);
    setErr(null);
    try {
      await api.transition(current.id, {
        to_status: to,
        reason: reason || undefined,
        recovered_amount: to === "recovered" ? recovered : undefined,
      });
      setReason("");
      setRecovered("");
      setOpen(null);
      await load();
    } catch (ex) {
      setErr(ex instanceof Error ? ex.message : "Transition failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="money">
        <article>
          <div className="k">Identified</div>
          <div className="v">{money("INR", bar.identified)}</div>
        </article>
        <article className="confirmed">
          <div className="k">Confirmed</div>
          <div className="v">{money("INR", bar.confirmed)}</div>
        </article>
        <article className="recovered">
          <div className="k">Recovered</div>
          <div className="v">{money("INR", bar.recovered)}</div>
        </article>
      </div>

      <div className="main">
        <section className="panel">
          <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem", flexWrap: "wrap" }}>
            <h2 style={{ margin: 0 }}>Exceptions</h2>
            <div className="btn-row">
              <select value={filter} onChange={(e) => setFilter(e.target.value)}>
                <option value="">All statuses</option>
                <option value="new">New</option>
                <option value="in_review">In review</option>
                <option value="confirmed">Confirmed</option>
                <option value="recovered">Recovered</option>
                <option value="dismissed">Dismissed</option>
              </select>
              <button className="btn btn-ghost" onClick={() => load()} disabled={busy}>
                Refresh
              </button>
              <button
                className="btn"
                disabled={!runId || busy}
                onClick={async () => {
                  if (!runId) return;
                  setBusy(true);
                  setErr(null);
                  try {
                    const pack = await api.makePack(runId);
                    await api.downloadPack(pack.id, pack.filename);
                    setPackMsg(`Pack ${pack.filename}`);
                  } catch (ex) {
                    setErr(ex instanceof Error ? ex.message : "Pack failed");
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                Download evidence pack
              </button>
            </div>
          </div>
          <p className="kbd">
            <kbd>j</kbd>/<kbd>k</kbd> move · <kbd>Enter</kbd> open · dismiss always needs a reason
          </p>
          {err && <p className="err">{err}</p>}
          {packMsg && <p className="hint">{packMsg}</p>}
          {!runId && (
            <p className="hint">
              Run rules from Import first if you want a pack tied to this session. You can still
              review any findings already in the tenant.
            </p>
          )}

          <table>
            <thead>
              <tr>
                <th>Rule</th>
                <th>Status</th>
                <th>Finding</th>
                <th>Amount</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr
                  key={row.id}
                  className={`click${i === sel ? " sel" : ""}`}
                  onClick={() => {
                    setSel(i);
                    void openRow(row.id);
                  }}
                >
                  <td>{row.rule}</td>
                  <td>
                    <span className={`pill ${row.status}`}>{row.status}</span>
                  </td>
                  <td>{row.title}</td>
                  <td className="amt">{money(row.currency, row.amount_at_risk)}</td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={4}>No exceptions yet. Import a file and run rules.</td>
                </tr>
              )}
            </tbody>
          </table>
        </section>

        {open && (
          <section className="panel detail">
            <div>
              <h2>{open.title}</h2>
              <p className="why">
                {String(open.explanation?.why ?? "See comparison below.")}
              </p>
              <pre className="hint" style={{ whiteSpace: "pre-wrap" }}>
                {JSON.stringify(open.explanation, null, 2)}
              </pre>
            </div>
            <div>
              <p>
                <span className={`pill ${open.status}`}>{open.status}</span> ·{" "}
                {money(open.currency, open.amount_at_risk)}
              </p>
              <label>
                Reason (required to dismiss)
                <textarea className="field" value={reason} onChange={(e) => setReason(e.target.value)} />
              </label>
              <label>
                Recovered amount
                <input className="field" value={recovered} onChange={(e) => setRecovered(e.target.value)} />
              </label>
              <div className="btn-row" style={{ marginTop: "0.75rem" }}>
                {open.status === "new" && (
                  <button className="btn btn-ghost" disabled={busy} onClick={() => move("in_review")}>
                    Start review
                  </button>
                )}
                {open.status === "in_review" && (
                  <button className="btn btn-ok" disabled={busy} onClick={() => move("confirmed")}>
                    Confirm
                  </button>
                )}
                {(open.status === "new" || open.status === "in_review") && (
                  <button className="btn btn-danger" disabled={busy} onClick={() => move("dismissed")}>
                    Dismiss
                  </button>
                )}
                {open.status === "confirmed" && (
                  <button className="btn btn-ok" disabled={busy} onClick={() => move("recovered")}>
                    Mark recovered
                  </button>
                )}
              </div>
            </div>
          </section>
        )}
      </div>
    </>
  );
}
