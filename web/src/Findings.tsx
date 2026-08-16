import { useCallback, useEffect, useState } from "react";
import { api, type ExceptionDetail, type ExceptionRow, type MoneyBar, type RunDesk } from "./api";

function money(currency: string, amount: string) {
  const n = Number(amount);
  if (Number.isNaN(n)) return `${currency} ${amount}`;
  return `${currency} ${n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

const STATUS: Record<string, string> = {
  new: "Not looked at yet",
  in_review: "You opened this",
  confirmed: "You said this is real",
  recovered: "Money came back",
  dismissed: "You said this is not a problem",
};

const QUEUE: { id: string; label: string }[] = [
  { id: "", label: "All questions" },
  { id: "integrity", label: "Possible mistakes" },
  { id: "match", label: "Confirm a payment" },
  { id: "completeness", label: "Missing / other month" },
];

const RULE_LABEL: Record<string, string> = {
  DUP_DOC: "Same invoice twice",
  DUP_REVISED: "Revised bill, same job",
  DUP_EXACT: "Exact duplicate",
  DUP_FUZZY: "Likely duplicate",
  DUP_VENDOR: "Same supplier, two names",
  MATCH_SUGGEST: "Possible payment",
  CREDIT_UNAPPLIED: "Credit note",
  OPEN_INVOICE: "Not in this bank file",
  OPEN_BANK: "Bank payment, no bill",
  COMP_2B_MISSING: "Not on GSTR-2B",
  COMP_2B_ORPHAN: "On GSTR-2B, no bill",
  AMT_2B: "Amount differs from GSTR-2B",
  BANK_CHANGE_PAY: "Bank account changed",
  NO_PO: "No purchase order",
  THRESHOLD: "Over threshold",
  VENDOR_IS_EMPLOYEE: "Vendor looks like staff",
};

function facts(explanation?: Record<string, unknown>) {
  if (!explanation) return [];
  return Object.entries(explanation).filter(([k]) => k !== "why" && k !== "rule");
}

export function Findings({ runId }: { runId: string | null }) {
  const [bar, setBar] = useState<MoneyBar>({
    identified: "0",
    completeness: "0",
    to_confirm: "0",
    confirmed: "0",
    recovered: "0",
  });
  const [rows, setRows] = useState<ExceptionRow[]>([]);
  const [family, setFamily] = useState("integrity");
  const [status, setStatus] = useState("new");
  const [sel, setSel] = useState(0);
  const [open, setOpen] = useState<ExceptionDetail | null>(null);
  const [reason, setReason] = useState("");
  const [recovered, setRecovered] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [packMsg, setPackMsg] = useState<string | null>(null);
  const [desk, setDesk] = useState<RunDesk["stats"] | null>(null);

  const load = useCallback(async () => {
    const data = await api.exceptions({
      ...(status ? { status } : {}),
      ...(family ? { family } : {}),
    });
    setBar({
      identified: data.identified,
      completeness: data.completeness ?? "0",
      to_confirm: data.to_confirm ?? "0",
      confirmed: data.confirmed,
      recovered: data.recovered,
      queues: data.queues,
    });
    setRows(data.exceptions);
    setSel((i) => Math.min(i, Math.max(0, data.exceptions.length - 1)));
    if (runId) {
      const run = await api.getRun(runId);
      setDesk(run.stats || {});
    }
  }, [family, status, runId]);

  useEffect(() => {
    load().catch((ex) => setErr(ex instanceof Error ? ex.message : "Could not load the desk"));
  }, [load]);

  const current = rows[sel];
  const ccy = current?.currency || open?.currency || "INR";
  const otherMonthIds = rows
    .filter((r) => r.status === "new" && Boolean(r.explanation?.other_period))
    .map((r) => r.id);

  async function openRow(id: string) {
    setErr(null);
    setOpen(await api.exception(id));
  }

  async function move(to: string, id?: string) {
    const target = id || open?.id || current?.id;
    if (!target) return;
    setBusy(true);
    setErr(null);
    try {
      await api.transition(target, {
        to_status: to,
        reason: to === "dismissed" ? reason || "Reviewed — not a finding" : reason || undefined,
        recovered_amount: to === "recovered" ? recovered : undefined,
      });
      setReason("");
      setRecovered("");
      if (open?.id === target) setOpen(null);
      await load();
    } catch (ex) {
      setErr(ex instanceof Error ? ex.message : "Could not save that decision");
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const tag = (e.target as HTMLElement | null)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if (!rows.length) return;
      if (e.key === "j" || e.key === "ArrowDown") {
        e.preventDefault();
        const next = Math.min(rows.length - 1, sel + 1);
        setSel(next);
        void openRow(rows[next].id);
      } else if (e.key === "k" || e.key === "ArrowUp") {
        e.preventDefault();
        const next = Math.max(0, sel - 1);
        setSel(next);
        void openRow(rows[next].id);
      } else if ((e.key === "c" || e.key === "Enter") && current && !busy) {
        e.preventDefault();
        if (e.key === "Enter" && !e.metaKey && !e.ctrlKey && current.id !== open?.id) {
          void openRow(current.id);
          return;
        }
        if (e.key === "c") {
          void (current.status === "new"
            ? move("in_review", current.id).then(() => move("confirmed", current.id))
            : move("confirmed", current.id));
        }
      } else if ((e.key === "x" || e.key === "d") && current && !busy) {
        e.preventDefault();
        void move("dismissed", current.id);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [rows, sel, current, busy, open?.id]);

  return (
    <>
      <div className="money four">
        <article>
          <div className="k">Possible mistakes</div>
          <div className="v">{money(ccy, bar.identified)}</div>
          <p className="s">
            {bar.queues?.integrity ?? 0} questions — same bill twice, a credit not applied, two names
            for one supplier
          </p>
        </article>
        <article>
          <div className="k">Confirm a payment</div>
          <div className="v">{money(ccy, bar.to_confirm)}</div>
          <p className="s">
            {bar.queues?.match ?? 0} bank lines that look like they settle a bill — only you can say yes
          </p>
        </article>
        <article>
          <div className="k">Missing / other month</div>
          <div className="v">{money(ccy, bar.completeness)}</div>
          <p className="s">
            {bar.queues?.completeness ?? 0} gaps — bill not on the GST portal, or a May bill vs a
            January bank file
          </p>
        </article>
        <article className="confirmed">
          <div className="k">You already decided</div>
          <div className="v">{money(ccy, bar.confirmed)}</div>
          <p className="s">Money marked back {money(ccy, bar.recovered)}</p>
        </article>
      </div>

      {desk?.briefing?.spoken && <p className="spoken">{desk.briefing.spoken}</p>}

      <div className="main">
        <section className="panel">
          <div className="toolbar">
            <div>
              <h2 style={{ margin: 0 }}>2. Answer each question</h2>
              <p className="hint" style={{ margin: "0.25rem 0 0" }}>
                Confirm = “this is real”. Dismiss = “this is not a problem”. Pulse never books a rupee.
              </p>
            </div>
            <div className="btn-row">
              <select value={status} onChange={(e) => setStatus(e.target.value)}>
                <option value="new">Not looked at yet</option>
                <option value="">Any status</option>
                <option value="in_review">You opened this</option>
                <option value="confirmed">You said this is real</option>
                <option value="dismissed">You said this is not a problem</option>
                <option value="recovered">Money came back</option>
              </select>
              {otherMonthIds.length > 0 && (
                <button
                  className="btn btn-ghost"
                  disabled={busy}
                  onClick={async () => {
                    setBusy(true);
                    setErr(null);
                    try {
                      await api.bulkTransition({
                        ids: otherMonthIds,
                        to_status: "dismissed",
                        reason: "other month",
                      });
                      await load();
                    } catch (ex) {
                      setErr(ex instanceof Error ? ex.message : "Could not dismiss other-month rows");
                    } finally {
                      setBusy(false);
                    }
                  }}
                >
                  Dismiss {otherMonthIds.length} other-month
                </button>
              )}
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

          {desk?.briefing && (
            <div className="guide start-here">
              <h3>Start here</h3>
              <p style={{ margin: "0 0 0.45rem", color: "var(--ink-2)" }}>{desk.briefing.voice || desk.briefing.start}</p>
              <ol>
                {desk.briefing.steps.map((step) => (
                  <li key={step}>{step}</li>
                ))}
              </ol>
              <p>{desk.briefing.guardrail}</p>
            </div>
          )}

          <div className="guide">
            <h3>What the words mean</h3>
            <ol>
              <li>
                <strong>Possible mistakes</strong> — same bill twice, a credit not applied, two names
                for one supplier.
              </li>
              <li>
                <strong>Confirm a payment</strong> — a bank line and a bill look related. Pulse will
                not treat them as paid until you say so.
              </li>
              <li>
                <strong>Missing / other month</strong> — a bill is not on the GST portal, or the bill
                and the bank file are from different months. Other month is not “unpaid”.
              </li>
            </ol>
            <p>
              Status: <em>Not looked at yet</em> → you have not opened it. <em>You said this is
              real</em> = confirm. <em>You said this is not a problem</em> = dismiss.
            </p>
          </div>

          <div className="queues">
            {QUEUE.map((q) => (
              <button
                key={q.id || "all"}
                className={family === q.id ? "on" : ""}
                onClick={() => setFamily(q.id)}
              >
                {q.label}
                <span>
                  {q.id === "integrity"
                    ? (bar.queues?.integrity ?? 0)
                    : q.id === "match"
                      ? (bar.queues?.match ?? 0)
                      : q.id === "completeness"
                        ? (bar.queues?.completeness ?? 0)
                        : (bar.queues?.all ?? rows.length)}
                </span>
              </button>
            ))}
          </div>

          {desk && (desk.invoices || desk.payments || desk.two_b || desk.ledger) ? (
            <p className="hint">
              Read {desk.invoices ?? 0} bills
              {desk.ledger_invoices ? ` (${desk.ledger_invoices} from the ledger)` : ""} ·{" "}
              {desk.payments ?? 0} payments · {desk.two_b ?? 0} GST portal rows ·{" "}
              {desk.open_invoices ?? 0} bills not in this bank file · {desk.two_b_gaps ?? 0} portal
              rows with no bill · {desk.credits ?? 0} credit notes
            </p>
          ) : (
            <div className="guide">
              <h3>Nothing to review yet</h3>
              <ol>
                <li>
                  Go to <strong>1. Load</strong>.
                </li>
                <li>Drop the customer zip or the files you have.</li>
                <li>
                  Press <strong>Review findings</strong>. That is what fills this page.
                </li>
              </ol>
              <p>An empty page is not a clean book. It means this session has not loaded a file set.</p>
            </div>
          )}
          <p className="kbd">
            <kbd>j</kbd>/<kbd>k</kbd> move · <kbd>c</kbd> confirm · <kbd>x</kbd> dismiss · other-month is not unpaid
          </p>
          {err && <p className="err">{err}</p>}
          {packMsg && <p className="ok-msg">{packMsg}</p>}

          <table>
            <thead>
              <tr>
                <th>Queue</th>
                <th>Finding</th>
                <th>Amount</th>
                <th></th>
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
                  <td>
                    <span className={`pill ${row.status}`}>{RULE_LABEL[row.rule] ?? row.rule.replaceAll("_", " ")}</span>
                  </td>
                  <td>{row.title}</td>
                  <td className="amt">{money(row.currency, row.amount_at_risk)}</td>
                  <td>
                    <div className="btn-row">
                      <button
                        className="btn btn-ok"
                        disabled={busy || row.status === "confirmed" || row.status === "recovered"}
                        onClick={(e) => {
                          e.stopPropagation();
                          void (row.status === "new" ? move("in_review", row.id).then(() => move("confirmed", row.id)) : move("confirmed", row.id));
                        }}
                      >
                        Confirm
                      </button>
                      <button
                        className="btn btn-ghost"
                        disabled={busy || row.status === "dismissed"}
                        onClick={(e) => {
                          e.stopPropagation();
                          void move("dismissed", row.id);
                        }}
                      >
                        Dismiss
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={4}>Nothing in this list. Try another group or status above.</td>
                </tr>
              )}
            </tbody>
          </table>
        </section>

        {open && (
          <section className="panel detail">
            <div>
              <h2>{open.title}</h2>
              <p className="why">{String(open.explanation?.why ?? "")}</p>
              {open.next_action && (
                <p className="next-action">
                  <strong>What you do: </strong>
                  {open.next_action}
                </p>
              )}
              {open.brain && <p className="hint">{open.brain}</p>}
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
              <label>
                Note / dismiss reason
                <textarea
                  className="field"
                  placeholder="Optional unless you dismiss"
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                />
              </label>
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
                  <button className="btn btn-ok" disabled={busy} onClick={() => move("in_review").then(() => move("confirmed"))}>
                    Confirm
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
