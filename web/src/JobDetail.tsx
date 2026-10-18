import { useCallback } from "react";
import { api, type JobDetail as Detail, type User } from "./api";
import { label, when, windowOf } from "./format";
import { usePolled } from "./usePolled";

export function JobDetail({ user, jobId }: { user: User; jobId: string }) {
  const load = useCallback(() => api(user).getJob(jobId), [user, jobId]);
  const [detail] = usePolled<Detail>(load);
  if (!detail) return <div className="card">Loading…</div>;

  const { job, request, quote } = detail;
  return (
    <div className="detail">
      <div className="card">
        <div className="title">
          <h2>
            {request.pickup_address.suburb} → {request.dropoff_address.suburb}
          </h2>
          <span className={`badge ${job.state}`}>{label(job.state)}</span>
        </div>
        <dl>
          <dt>Job</dt>
          <dd className="mono">{job.job_id}</dd>
          <dt>Request</dt>
          <dd className="mono">{request.request_id}</dd>
          <dt>Customer</dt>
          <dd>{job.customer_id}</dd>
          <dt>Contact</dt>
          <dd>
            {request.contact_name}, {request.contact_phone}
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
          <dt>Created</dt>
          <dd>{when(job.created_at)}</dd>
        </dl>
      </div>

      <div className="card">
        <h3>Accepted quote</h3>
        <div className="quote">
          <div className="title">
            <strong>${quote.price}</strong>
          </div>
          <div className="muted">
            Pickup {windowOf(quote.eta_pickup)} · Drop-off {windowOf(quote.eta_dropoff)}
          </div>
          <div className="muted">
            Issued by {quote.issued_by} · accepted {quote.responded_at && when(quote.responded_at)}
          </div>
        </div>
      </div>
    </div>
  );
}
