import { useCallback, useState } from "react";
import { api, type NewQuote, type RequestDetail as Detail, type User } from "./api";
import { iso, label, local, when, windowOf } from "./format";
import { usePolled } from "./usePolled";

type Run = (action: () => Promise<unknown>) => Promise<boolean>;

type Props = { user: User; requestId: string; run: Run; onAccepted: (jobId: string) => void };

export function RequestDetail({ user, requestId, run, onAccepted }: Props) {
  const load = useCallback(() => api(user).getRequest(requestId), [user, requestId]);
  const [detail, refresh] = usePolled<Detail>(load);
  if (!detail) return <div className="card">Loading…</div>;

  const { request, quotes, history } = detail;
  const open = request.status === "open";
  const act = (action: () => Promise<unknown>) => run(action).then((ok) => (refresh(), ok));

  return (
    <div className="detail">
      <div className="card">
        <div className="title">
          <h2>
            {request.pickup_address.suburb} → {request.dropoff_address.suburb}
          </h2>
          <span className={`badge ${request.status}`}>{request.status}</span>
        </div>
        <dl>
          <dt>Request</dt>
          <dd className="mono">{request.request_id}</dd>
          <dt>Contact</dt>
          <dd>
            {request.contact_name}, {request.contact_phone}
          </dd>
          <dt>Customer</dt>
          <dd>
            {request.customer_id ?? "anonymous"}
            {request.logged_by && ` (logged by ${request.logged_by})`}
          </dd>
          <dt>Parcels</dt>
          <dd>{request.parcels.map((p) => `${p.quantity}× ${p.size}, ${p.weight_kg} kg`).join("; ")}</dd>
          <dt>Pickup</dt>
          <dd>
            {request.pickup_address.street}, {request.pickup_address.suburb} {request.pickup_address.postcode}
          </dd>
          <dt>Drop-off</dt>
          <dd>
            {request.dropoff_address.street}, {request.dropoff_address.suburb} {request.dropoff_address.postcode}
          </dd>
          <dt>Logged</dt>
          <dd>{when(request.created_at)}</dd>
        </dl>
        {open && (
          <button className="danger" onClick={() => act(() => api(user).cancel(request.request_id))}>
            Cancel request
          </button>
        )}
      </div>

      {user.role === "staff" && open && (
        <IssueQuote onSubmit={(body) => act(() => api(user).issueQuote(request.request_id, body))} superseding={!!request.current_quote_id} />
      )}

      <div className="card">
        <h3>Quotes</h3>
        {quotes.length === 0 && <p className="muted">No quotes yet.</p>}
        {quotes.map((q) => {
          const live = open && q.quote_id === request.current_quote_id && q.status === "pending";
          const expired = new Date(q.expiry_time) <= new Date();
          return (
            <div key={q.quote_id} className={`quote ${live ? "live" : ""}`}>
              <div className="title">
                <strong>${q.price}</strong>
                <span className={`badge ${q.status}`}>{label(q.status)}</span>
                {live && expired && <span className="badge cancelled">expired</span>}
              </div>
              <div className="muted">
                Pickup {windowOf(q.eta_pickup)} · Drop-off {windowOf(q.eta_dropoff)}
              </div>
              <div className="muted">
                Issued {when(q.time_of_issue)} by {q.issued_by} · valid until {when(q.expiry_time)}
              </div>
              {live && !expired && user.role === "customer" && (
                <div className="actions">
                  <button
                    className="primary"
                    onClick={() => act(async () => onAccepted((await api(user).accept(request.request_id, q.quote_id)).job_id))}
                  >
                    Accept
                  </button>
                  <button onClick={() => act(() => api(user).reject(request.request_id, q.quote_id))}>Reject</button>
                </div>
              )}
            </div>
          );
        })}
      </div>

      <div className="card">
        <h3>History</h3>
        <ol className="history">
          {history.map((e) => (
            <li key={e.id}>
              <strong>{label(e.event_type)}</strong> by {e.created_by ?? "anonymous"}
              <span className="muted"> · {when(e.created_at)}</span>
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}

// datetime-local inputs, defaulting to a pickup 1–3 h and a drop-off 4–6 h from now
function IssueQuote({ onSubmit, superseding }: { onSubmit: (body: NewQuote) => Promise<boolean>; superseding: boolean }) {
  const [price, setPrice] = useState("");
  const [times, setTimes] = useState(() => [local(1), local(3), local(4), local(6)]);
  const setTime = (i: number, value: string) => setTimes(times.map((t, j) => (j === i ? value : t)));

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const ok = await onSubmit({ price, eta_pickup: [iso(times[0]), iso(times[1])], eta_dropoff: [iso(times[2]), iso(times[3])] });
    if (ok) setPrice("");
  }

  return (
    <form className="card" onSubmit={submit}>
      <h3>{superseding ? "Issue a new quote (replaces the current one)" : "Issue a quote"}</h3>
      <input placeholder="Price (AUD)" value={price} onChange={(e) => setPrice(e.target.value)} />
      <label>Pickup window</label>
      <div className="row">
        <input type="datetime-local" value={times[0]} onChange={(e) => setTime(0, e.target.value)} />
        <input type="datetime-local" value={times[1]} onChange={(e) => setTime(1, e.target.value)} />
      </div>
      <label>Drop-off window</label>
      <div className="row">
        <input type="datetime-local" value={times[2]} onChange={(e) => setTime(2, e.target.value)} />
        <input type="datetime-local" value={times[3]} onChange={(e) => setTime(3, e.target.value)} />
      </div>
      <button type="submit" className="primary">Issue quote</button>
    </form>
  );
}

