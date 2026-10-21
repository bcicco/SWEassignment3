import { useCallback, useState, type FormEvent } from "react";
import { api, type DeliveryJob, type NewAdjustment, type NewPayment, type Payment, type PaymentDetail, type PaymentMethod, type PaymentOutcome, type User } from "./api";
import { label, money, shortId, when } from "./format";
import { usePolled } from "./usePolled";

type Run = (action: () => Promise<unknown>) => Promise<boolean>;

// the states a job's driver can take money in (A2 JobState cards); a closed job takes none
const PAYABLE = ["allocated", "in_transit", "on_hold", "delivered"];

// Task 7: what the job owes, what's been collected, and closing it once paid and delivered
export function PaymentPanel({ user, job, run, onChanged }: { user: User; job: DeliveryJob; run: Run; onChanged: () => void }) {
  const load = useCallback(() => api(user).payments(job.job_id), [user, job.job_id]);
  const [detail, refresh] = usePolled<PaymentDetail>(load, 3000);
  const act = (action: () => Promise<unknown>) => run(action).then((ok) => (refresh(), onChanged(), ok));

  if (!detail) return <div className="card muted">Loading payment…</div>;
  const { settlement, payments, adjustments } = detail;
  const outstanding = Number(settlement.outstanding);
  const client = api(user);

  return (
    <div className="card">
      <div className="title">
        <h3>Payment</h3>
        <span className={`badge ${settlement.resolved ? "accepted" : "pending"}`}>{settlement.resolved ? "resolved" : "unresolved"}</span>
      </div>
      <dl>
        <dt>Amount due</dt>
        <dd>
          {money(settlement.amount_due)} <span className="muted">from the accepted quote</span>
        </dd>
        <dt>Collected</dt>
        <dd>{money(settlement.net_collected)}</dd>
        <dt>Outstanding</dt>
        <dd>
          {money(outstanding)}
          {outstanding < 0 && <span className="muted"> over-collected; office staff must correct it</span>}
        </dd>
      </dl>

      {user.role === "driver" && job.delivery_staff_id === user.id && PAYABLE.includes(job.state) && outstanding > 0 && (
        <RecordPayment key={settlement.revision} due={settlement.outstanding} onSubmit={(body) => act(() => client.recordPayment(job.job_id, body))} />
      )}

      {user.role === "staff" && job.state !== "closed" && payments.length > 0 && (
        <AdjustPayment
          key={`adjust-${settlement.revision}`}
          payments={payments}
          onSubmit={(paymentId, body) => act(() => client.adjustPayment(job.job_id, paymentId, body))}
        />
      )}

      {user.role === "staff" && job.state === "delivered" && (
        <div className="actions">
          <button
            className="primary"
            onClick={() => confirm("Close this job? A closed job can't take further payments or attempts.") && act(() => client.closeJob(job.job_id))}
          >
            Close job
          </button>
          {!settlement.resolved && <span className="muted">The payment must be resolved before the job can close.</span>}
        </div>
      )}
      {job.state === "closed" && <p className="muted">This job is closed. Its records stay available for review.</p>}

      <h3>Payments</h3>
      {payments.length === 0 && <p className="muted">No payments recorded.</p>}
      <ol className="history">
        {payments.map((p) => (
          <li key={p.id}>
            <strong>{label(p.outcome)}</strong> {p.method ?? ""} {money(p.amount)} of {money(p.amount_due)} due
            <span className="muted">
              {" "}
              · by {p.created_by} · {when(p.created_at)} · <span className="mono">{shortId(p.id)}</span>
            </span>
            {Number(p.variance) !== 0 && <span className="tag">variance {money(p.variance)}</span>}
            {p.reason && <div className="muted">Reason: {p.reason}</div>}
          </li>
        ))}
      </ol>
      {adjustments.length > 0 && (
        <>
          <h3>Adjustments</h3>
          <ol className="history">
            {adjustments.map((a) => (
              <li key={a.id}>
                {Number(a.amount) > 0 ? "+" : ""}
                {money(a.amount)} {a.method}
                {a.provider_reference && ` (ref ${a.provider_reference})`} to payment <span className="mono">{shortId(a.payment_id)}</span>
                <span className="muted">
                  {" "}
                  · by {a.created_by} · {when(a.created_at)}
                </span>
                <div className="muted">Reason: {a.reason}</div>
              </li>
            ))}
          </ol>
        </>
      )}
    </div>
  );
}

// The driver's payment step. The amount to collect comes from the quote, so it's never
// worked out by hand; anything less needs a reason (Task 7 3a). The id is kept until the
// payment is saved, so retrying after a lost response can't record it twice
function RecordPayment({ due, onSubmit }: { due: string; onSubmit: (body: NewPayment) => Promise<boolean> }) {
  const [paymentId] = useState(() => crypto.randomUUID());
  const [outcome, setOutcome] = useState<PaymentOutcome>("collected");
  const [method, setMethod] = useState<PaymentMethod>("cash");
  const [amount, setAmount] = useState(Number(due).toFixed(2));
  const [reason, setReason] = useState("");
  const collected = outcome === "collected";
  const variance = collected && amount !== "" ? Number(amount) - Number(due) : 0;
  const needsReason = !collected || variance < 0;

  function clear() {
    setOutcome("collected");
    setMethod("cash");
    setAmount(Number(due).toFixed(2));
    setReason("");
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    const summary = collected ? `${money(amount)} ${method}` : outcome === "declined" ? "a declined card" : "a refused payment";
    if (!confirm(`Record ${summary}? A payment can't be edited once recorded.`)) return;
    const body: NewPayment = {
      payment_id: paymentId,
      outcome,
      method: outcome === "refused" ? null : outcome === "declined" ? "card" : method,
      amount: collected ? amount : "0",
    };
    if (reason.trim()) body.reason = reason;
    onSubmit(body);
  }

  return (
    <form onSubmit={submit} onReset={clear}>
      <fieldset>
        <legend>Record payment · {money(due)} to collect</legend>
        <label>
          Outcome
          <select value={outcome} onChange={(e) => setOutcome(e.target.value as PaymentOutcome)}>
            <option value="collected">Collected</option>
            <option value="declined">Card declined by the payment device</option>
            <option value="refused">Customer refused or unable to pay</option>
          </select>
        </label>
        {collected && (
          <div className="row">
            <label>
              Method
              <select value={method} onChange={(e) => setMethod(e.target.value as PaymentMethod)}>
                <option value="cash">Cash</option>
                <option value="card">Card (on the payment device)</option>
              </select>
            </label>
            <label>
              Amount collected (AUD)
              <input type="number" min="0.01" step="0.01" required value={amount} onChange={(e) => setAmount(e.target.value)} />
            </label>
          </div>
        )}
        {variance !== 0 && <p className="tag">Variance {money(variance)}. Office staff will be notified.</p>}
        <label>
          Reason{needsReason ? " (required)" : " (optional)"}
          <input value={reason} required={needsReason} maxLength={1000} onChange={(e) => setReason(e.target.value)} />
        </label>
        <p className="muted">For card, record only the device's outcome. Never enter card details.</p>
        <div className="actions">
          <button type="submit" className="primary">
            Record payment
          </button>
          <button type="reset">Clear draft</button>
        </div>
      </fieldset>
    </form>
  );
}

// Task 7 4a: office staff append a balance (+) or correction (−) to a payment
function AdjustPayment({ payments, onSubmit }: { payments: Payment[]; onSubmit: (paymentId: string, body: NewAdjustment) => Promise<boolean> }) {
  const [adjustmentId] = useState(() => crypto.randomUUID());
  const [paymentId, setPaymentId] = useState(payments[payments.length - 1].id);
  const [amount, setAmount] = useState("");
  const [method, setMethod] = useState<PaymentMethod>("card");
  const [reference, setReference] = useState("");
  const [reason, setReason] = useState("");

  function clear() {
    setPaymentId(payments[payments.length - 1].id);
    setAmount("");
    setMethod("card");
    setReference("");
    setReason("");
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    if (!confirm(`Add an adjustment of ${money(amount)} ${method}? It can't be edited once recorded.`)) return;
    const body: NewAdjustment = { adjustment_id: adjustmentId, amount, method, reason };
    if (reference.trim()) body.provider_reference = reference;
    onSubmit(paymentId, body);
  }

  return (
    <form onSubmit={submit} onReset={clear}>
      <fieldset>
        <legend>Adjust a payment (balance or correction)</legend>
        <label>
          Payment
          <select value={paymentId} onChange={(e) => setPaymentId(e.target.value)}>
            {payments.map((p) => (
              <option key={p.id} value={p.id}>
                {shortId(p.id)}: {label(p.outcome)} {money(p.amount)} by {p.created_by}
              </option>
            ))}
          </select>
        </label>
        <div className="row">
          <label>
            Amount (AUD, negative to correct)
            <input type="number" step="0.01" required value={amount} onChange={(e) => setAmount(e.target.value)} />
          </label>
          <label>
            Method
            <select value={method} onChange={(e) => setMethod(e.target.value as PaymentMethod)}>
              <option value="card">Card</option>
              <option value="cash">Cash</option>
            </select>
          </label>
        </div>
        <label>
          Payment device reference{method === "card" ? " (required)" : " (optional)"}
          <input value={reference} required={method === "card"} maxLength={200} onChange={(e) => setReference(e.target.value)} />
        </label>
        <label>
          Reason (required)
          <input value={reason} required maxLength={1000} onChange={(e) => setReason(e.target.value)} />
        </label>
        <div className="actions">
          <button type="submit" className="primary">
            Add adjustment
          </button>
          <button type="reset">Clear draft</button>
        </div>
      </fieldset>
    </form>
  );
}
