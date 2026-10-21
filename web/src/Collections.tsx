import { useCallback, useState } from "react";
import { api, type CollectionTotals, type User } from "./api";
import { label, money, shortId, when } from "./format";
import { usePolled } from "./usePolled";

// today as a date input's value, in local time
const today = () => new Date().toLocaleDateString("en-CA");

// Task 7 variant 5a: one person's collections on one day, split by method so cash on hand
// and card totals can be reconciled (QA3.6). Drivers see only their own
export function Collections({ user }: { user: User }) {
  const [staffId, setStaffId] = useState(user.role === "driver" ? user.id : "driver-1");
  const [day, setDay] = useState(today);
  const load = useCallback(() => api(user).collections(staffId, day), [user, staffId, day]);
  const [totals] = usePolled<CollectionTotals>(load);
  const current = totals?.staff_id === staffId && totals.day === day ? totals : undefined;

  return (
    <div className="detail">
      <div className="card">
        <h3>Daily collections</h3>
        <div className="row">
          <label>
            Staff member
            <input value={staffId} disabled={user.role === "driver"} onChange={(e) => setStaffId(e.target.value.trim())} />
          </label>
          <label>
            Day
            <input type="date" value={day} required onChange={(e) => setDay(e.target.value)} />
          </label>
        </div>
        {current && (
          <dl>
            <dt>Cash</dt>
            <dd>{money(current.cash)}</dd>
            <dt>Card</dt>
            <dd>{money(current.card)}</dd>
          </dl>
        )}
      </div>

      {current && (
        <div className="card">
          <h3>Payments</h3>
          {current.payments.length === 0 && <p className="muted">None on this day.</p>}
          <ol className="history">
            {current.payments.map((p) => (
              <li key={p.id}>
                {label(p.outcome)} {p.method ?? ""} {money(p.amount)}
                <span className="muted">
                  {" "}
                  · job <span className="mono">{shortId(p.job_id)}</span> · {when(p.created_at)}
                </span>
              </li>
            ))}
          </ol>
          <h3>Adjustments</h3>
          {current.adjustments.length === 0 && <p className="muted">None on this day.</p>}
          <ol className="history">
            {current.adjustments.map((a) => (
              <li key={a.id}>
                {money(a.amount)} {a.method}
                <span className="muted">
                  {" "}
                  · job <span className="mono">{shortId(a.job_id)}</span> · {when(a.created_at)} · {a.reason}
                </span>
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}
