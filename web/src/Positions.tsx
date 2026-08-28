/* Supplier positions -- what replaces the exception queue.
 *
 * From the 16 Aug call: match-match-match is "just another clerical
 * reconciliation", and Zoho already gets there without AI. So the first screen
 * is one row per supplier. Transactions exist, but only after someone clicks
 * into a supplier and asks for them.
 *
 * There is no confirm or dismiss on this screen, deliberately. A position is
 * computed from documents; it is not something a person signs off.
 */

import { useEffect, useState } from "react";
import { api, ApiError, type PositionDetail, type PositionList, type SupplierPosition } from "./api";

function money(currency: string, raw: string): string {
  const n = Number(raw);
  if (!Number.isFinite(n)) return raw;
  return `${currency} ${Math.abs(n).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

function Pill({ state }: { state: SupplierPosition["state"] }) {
  const label = state === "clear" ? "clear" : state === "waiting" ? "waiting" : "needs attention";
  return <span className={`pos-pill pos-${state}`}>{label}</span>;
}

function Detail({ identityId, onBack }: { identityId: string; onBack: () => void }) {
  const [d, setD] = useState<PositionDetail | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    let live = true;
    api
      .positionDetail(identityId)
      .then((x) => live && setD(x))
      .catch((e) => live && setErr(e instanceof ApiError ? e.message : "Could not load that supplier."));
    return () => {
      live = false;
    };
  }, [identityId]);

  if (err) return <p className="hint">{err}</p>;
  if (!d) return <p className="hint">Loading…</p>;

  return (
    <section className="card">
      <button className="btn btn-ghost" onClick={onBack}>
        ← All suppliers
      </button>

      <h2 style={{ marginBottom: 4 }}>{d.name}</h2>
      <p className="hint" style={{ marginTop: 0 }}>
        <Pill state={d.state} /> {d.headline}
      </p>

      <div className="pos-figures">
        <div>
          <span className="k">Invoiced</span>
          <span className="v">{money(d.currency, d.invoiced)}</span>
        </div>
        <div>
          <span className="k">Paid</span>
          <span className="v">{money(d.currency, d.paid)}</span>
        </div>
        {Number(d.credit_notes) !== 0 && (
          <div>
            <span className="k">Credit notes</span>
            <span className="v">{money(d.currency, d.credit_notes)}</span>
          </div>
        )}
        {Number(d.difference) !== 0 && (
          <div>
            <span className="k">Difference</span>
            <span className="v">{money(d.currency, d.difference)}</span>
          </div>
        )}
      </div>

      {d.unexplained_payments > 0 && (
        <p className="hint">
          {d.unexplained_payments} payment(s) here could not be tied to an invoice in this drop.
        </p>
      )}

      <h3>Bills ({d.invoices.length})</h3>
      <table className="tbl">
        <tbody>
          {d.invoices.map((i, n) => (
            <tr key={`${i.number}-${n}`}>
              <td>{i.number}</td>
              <td>{i.date ?? "—"}</td>
              <td className="amt">{money(i.currency, i.amount)}</td>
            </tr>
          ))}
          {d.invoices.length === 0 && (
            <tr>
              <td colSpan={3}>No bills for this supplier in this drop.</td>
            </tr>
          )}
        </tbody>
      </table>

      <h3>Payments ({d.payments.length})</h3>
      <table className="tbl">
        <tbody>
          {d.payments.map((p, n) => (
            <tr key={n}>
              <td>{p.date ?? "—"}</td>
              <td>{p.reference ?? "—"}</td>
              <td className="amt">{money(p.currency, p.amount)}</td>
            </tr>
          ))}
          {d.payments.length === 0 && (
            <tr>
              <td colSpan={3}>No payments for this supplier in this drop.</td>
            </tr>
          )}
        </tbody>
      </table>

      {d.credit_notes_list.length > 0 && (
        <>
          <h3>Credit notes ({d.credit_notes_list.length})</h3>
          <table className="tbl">
            <tbody>
              {d.credit_notes_list.map((c, n) => (
                <tr key={n}>
                  <td>{c.ref}</td>
                  <td>{c.date ?? "—"}</td>
                  <td className="amt">{money(d.currency, c.amount)}</td>
                  <td>{c.applied ? "applied" : "not seen applied"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </section>
  );
}

export function Positions() {
  const [list, setList] = useState<PositionList | null>(null);
  const [err, setErr] = useState("");
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api
      .positions()
      .then((x) => live && setList(x))
      .catch((e) => live && setErr(e instanceof ApiError ? e.message : "Could not load suppliers."));
    return () => {
      live = false;
    };
  }, []);

  if (open) return <Detail identityId={open} onBack={() => setOpen(null)} />;
  if (err) return <p className="hint">{err}</p>;
  if (!list) return <p className="hint">Loading…</p>;

  if (list.checked === 0) {
    return (
      <section className="card">
        <h2>No suppliers yet</h2>
        <p className="hint">
          Drop a zip on <strong>1. Load</strong> first. Pulse reads the bills, payments and bank lines,
          then shows where you stand with each supplier.
        </p>
      </section>
    );
  }

  return (
    <section className="card">
      <h2 style={{ marginBottom: 4 }}>Where you stand</h2>
      <p className="spoken">{list.headline}</p>

      <table className="tbl pos-tbl">
        <thead>
          <tr>
            <th>Supplier</th>
            <th>Position</th>
            <th className="amt">Invoiced</th>
            <th className="amt">Paid</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {list.positions.map((p) => (
            <tr key={p.identity_id} className={`pos-row pos-${p.state}`}>
              <td>
                <strong>{p.name}</strong>
                <div className="hint" style={{ margin: 0 }}>
                  {p.invoice_count} bill(s) · {p.payment_count} payment(s)
                </div>
              </td>
              <td>
                <Pill state={p.state} /> {p.state !== "clear" && p.headline}
              </td>
              <td className="amt">{money(p.currency, p.invoiced)}</td>
              <td className="amt">{money(p.currency, p.paid)}</td>
              <td>
                <button className="btn btn-ghost" onClick={() => setOpen(p.identity_id)}>
                  Open
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <p className="hint">
        Nothing to confirm here. These are computed from the documents you dropped — open a supplier to
        see the bills and payments behind a number.
      </p>
    </section>
  );
}
