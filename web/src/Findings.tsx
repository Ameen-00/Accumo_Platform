import { useCallback, useEffect, useState } from "react";
import { api, type ExceptionDetail, type ExceptionRow, type MoneyBar } from "./api";

function money(currency: string, amount: string) {
  const n = Number(amount);
  if (Number.isNaN(n)) return `${currency} ${amount}`;
  return `${currency} ${n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

const STATUS: Record<string, string> = {
  new: "New",
  in_review: "In review",
  confirmed: "Confirmed",
  recovered: "Recovered",
  dismissed: "Dismissed",
};

function facts(explanation?: Record<string, unknown>) {
  if (!explanation) return [];
  return Object.entries(explanation).filter(([k]) => k !== "why" && k !== "rule");
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
  const ccy = current?.currency || open?.currency || "INR";

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
    const id = open?.id || current?.id;
    if (!id) return;
    setBusy(true);
    setErr(null);
    try {
      await api.transition(id, {
        to_status: to,
        reason: reason || undefined,
        recovered_amount: to === "recovered" ? recovered : undefined,
      });
      setReason("");
      setRecovered("");
      setOpen(null);
      await load();
    } catch (ex) {
      setErr(ex instanceof Error ? ex.message : "Could not save that decision");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="money">
        <article>
          <div className="k">Identified</div>
          <div className="v">{money(ccy, bar.identified)}</div>
          <p className="s">Flagged. Not yet agreed.</p>
        </article>
        <article className="confirmed">
          <div className="k">Confirmed</div>
          <div className="v">{money(ccy, bar.confirmed)}</div>
          <p className="s">You said this is real.</p>
        </article>
        <article className="recovered">
          <div className="k">Recovered</div>
          <div className="v">{money(ccy, bar.recovered)}</div>
          <p className="s">Money recorded as back.</p>
        </article>
      </div>

      <div className="main">
        <section className="panel">
          <div className="toolbar">
            <div>
              <h2 style={{ margin: 0 }}>Findings</h2>
              <p className="hint" style={{ margin: "0.25rem 0 0" }}>
                Click a row. Confirm if it is real. Dismiss only with a reason.
              </p>
            </div>
            <div className="btn-row">
              <select value={filter} onChange={(e) => setFilter(e.target.value)}>
                <option value="">All</option>
                <option value="new">New</option>
                <option value="in_review">In review</option>
                <option value="confirmed">Confirmed</option>
                <option value="recovered">Recovered</option>
                <option value="dismissed">Dismissed</option>
              </select>
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
                    setPackMsg(`Saved ${pack.filename}`);
                  } catch (ex) {
                    setErr(ex instanceof Error ? ex.message : "Could not build the pack");
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                Download pack
              </button>
            </div>
          </div>
          {err && <p className="err">{err}</p>}
          {packMsg && <p className="ok-msg">{packMsg}</p>}
          {!runId && (
            <p className="hint">To attach a pack to this session, run Find issues from Import first.</p>
          )}

          <table>
            <thead>
              <tr>
                <th>What it is</th>
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
                  <td>{row.rule.replaceAll("_", " ")}</td>
                  <td>
                    <span className={`pill ${row.status}`}>{STATUS[row.status] ?? row.status}</span>
                  </td>
                  <td>{row.title}</td>
                  <td className="amt">{money(row.currency, row.amount_at_risk)}</td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={4}>Nothing here yet. Load books on Import, then Find issues.</td>
                </tr>
              )}
            </tbody>
          </table>
        </section>

        {open && (
          <section className="panel detail">
            <div>
              <h2>{open.title}</h2>
              <p className="why">{String(open.explanation?.why ?? "Open the row details below.")}</p>
              {facts(open.explanation).length > 0 && (
                <dl className="facts">
                  {facts(open.explanation).map(([k, v]) => (
                    <div key={k}>
                      <dt>{k.replaceAll("_", " ")}</dt>
                      <dd>{Array.isArray(v) ? v.join(", ") : String(v)}</dd>
                    </div>
                  ))}
                </dl>
              )}
            </div>
            <div className="decide">
              <p>
                <span className={`pill ${open.status}`}>{STATUS[open.status] ?? open.status}</span>{" "}
                <strong>{money(open.currency, open.amount_at_risk)}</strong>
              </p>
              {(open.status === "new" || open.status === "in_review") && (
                <label>
                  Why dismiss? (required if you dismiss)
                  <textarea
                    className="field"
                    placeholder="e.g. instalment, same payment listed twice, known advance"
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                  />
                </label>
              )}
              {open.status === "confirmed" && (
                <label>
                  How much came back
                  <input
                    className="field"
                    placeholder="e.g. 120000"
                    value={recovered}
                    onChange={(e) => setRecovered(e.target.value)}
                  />
                </label>
              )}
              <div className="btn-row" style={{ marginTop: "0.75rem" }}>
                {open.status === "new" && (
                  <button className="btn btn-ghost" disabled={busy} onClick={() => move("in_review")}>
                    Start review
                  </button>
                )}
                {open.status === "in_review" && (
                  <button className="btn btn-ok" disabled={busy} onClick={() => move("confirmed")}>
                    This is real
                  </button>
                )}
                {(open.status === "new" || open.status === "in_review") && (
                  <button className="btn btn-danger" disabled={busy} onClick={() => move("dismissed")}>
                    Not a finding
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
