import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError, type DeliveryRequest, type JobState, type JobSummary, type RequestStatus, type Role, type User } from "./api";
import { label, shortId, when } from "./format";
import { JobDetail } from "./JobDetail";
import { RequestDetail } from "./RequestDetail";
import { RequestForm } from "./RequestForm";
import { usePolled } from "./usePolled";

// no login yet: pick who to act as (kept across reloads)
function useActingAs(): [User, (user: User) => void] {
  const [user, setUser] = useState<User>(() => JSON.parse(localStorage.getItem("user") ?? "null") ?? { id: "cust-1", role: "customer" });
  useEffect(() => localStorage.setItem("user", JSON.stringify(user)), [user]);
  return [user, setUser];
}

type Tab = "requests" | "jobs";

// accepted requests are listed as jobs instead
const REQUEST_FILTERS = [undefined, "open", "cancelled"] as const;
const JOB_FILTERS = [undefined, "unallocated", "allocated", "in_transit", "on_hold", "delivered", "closed"] as const;

const ERROR_HINTS: Record<number, string> = { 409: "Someone else changed this first. It has been reloaded; try again." };

export default function App() {
  const [user, setUser] = useActingAs();
  const [idDraft, setIdDraft] = useState(user.id);
  const [tab, setTab] = useState<Tab>("requests");
  const [status, setStatus] = useState<RequestStatus | undefined>(user.role === "staff" ? "open" : undefined);
  const [jobState, setJobState] = useState<JobState | undefined>(user.role === "staff" ? "unallocated" : undefined);
  const [selected, setSelected] = useState<string>();
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string>();

  const client = useMemo(() => api(user), [user]);
  const loadRequests = useCallback(
    async () => (tab === "requests" ? (await client.listRequests(status)).filter((r) => r.status !== "accepted") : []),
    [client, tab, status],
  );
  const loadJobs = useCallback(async () => (tab === "jobs" ? client.listJobs(jobState) : []), [client, tab, jobState]);
  const [requests, refreshRequests] = usePolled<DeliveryRequest[]>(loadRequests);
  const [jobs, refreshJobs] = usePolled<JobSummary[]>(loadJobs);
  const refresh = useCallback(() => (refreshRequests(), refreshJobs()), [refreshRequests, refreshJobs]);

  function switchTo(next: User) {
    setUser(next);
    setIdDraft(next.id);
    setSelected(undefined);
    setStatus(next.role === "staff" ? "open" : undefined);
    setJobState(next.role === "staff" ? "unallocated" : undefined);
  }

  function showTab(next: Tab, select?: string) {
    setTab(next);
    setSelected(select);
    setCreating(false);
  }

  // runs a command, shows any refusal, and reloads the list either way
  const run = useCallback(
    async (action: () => Promise<unknown>) => {
      try {
        await action();
        setError(undefined);
        return true;
      } catch (e) {
        setError(e instanceof ApiError ? `${ERROR_HINTS[e.status] ?? ""} ${e.message}`.trim() : String(e));
        return false;
      } finally {
        refresh();
      }
    },
    [refresh],
  );

  return (
    <>
      <header>
        <div className="acting-as">
          <span>Acting as</span>
          <select value={user.role} onChange={(e) => switchTo({ id: e.target.value === "staff" ? "staff-1" : "cust-1", role: e.target.value as Role })}>
            <option value="customer">Customer</option>
            <option value="staff">Office staff</option>
          </select>
          <input
            value={idDraft}
            onChange={(e) => setIdDraft(e.target.value)}
            onBlur={() => idDraft && idDraft !== user.id && switchTo({ ...user, id: idDraft })}
            onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
          />
        </div>
      </header>

      {error && (
        <div className="error" onClick={() => setError(undefined)}>
          {error}
        </div>
      )}

      <main>
        <aside>
          <button className="primary wide" onClick={() => (showTab("requests"), setCreating(true))}>
            + New request
          </button>
          <nav className="tabs">
            {(["requests", "jobs"] as const).map((t) => (
              <button key={t} className={tab === t ? "active" : ""} onClick={() => showTab(t)}>
                {t === "requests" ? "Delivery requests" : "Delivery jobs"}
              </button>
            ))}
          </nav>
          {tab === "requests" ? (
            <>
              <nav className="filters">
                {REQUEST_FILTERS.map((s) => (
                  <button key={s ?? "all"} className={status === s ? "active" : ""} onClick={() => setStatus(s)}>
                    {s ? label(s) : "all"}
                  </button>
                ))}
              </nav>
              {requests?.length === 0 && <p className="muted">No requests.</p>}
              <ul className="list">
                {requests?.map((r) => (
                  <li
                    key={r.request_id}
                    className={r.request_id === selected ? "selected" : ""}
                    onClick={() => (setSelected(r.request_id), setCreating(false))}
                  >
                    <div className="title">
                      <strong>
                        {r.pickup_address.suburb} → {r.dropoff_address.suburb}
                      </strong>
                      <span className={`badge ${r.status}`}>{r.status}</span>
                    </div>
                    <div className="muted">
                      {r.contact_name} · {when(r.created_at)} · <span className="mono">{shortId(r.request_id)}</span>
                    </div>
                    {user.role === "staff" && r.status === "open" && !r.current_quote_id && <div className="tag">needs a quote</div>}
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <>
              <nav className="filters wrap">
                {JOB_FILTERS.map((s) => (
                  <button key={s ?? "all"} className={jobState === s ? "active" : ""} onClick={() => setJobState(s)}>
                    {s ? label(s) : "all"}
                  </button>
                ))}
              </nav>
              {jobs?.length === 0 && <p className="muted">No jobs.</p>}
              <ul className="list">
                {jobs?.map(({ job, request }) => (
                  <li key={job.job_id} className={job.job_id === selected ? "selected" : ""} onClick={() => setSelected(job.job_id)}>
                    <div className="title">
                      <strong>
                        {request.pickup_address.suburb} → {request.dropoff_address.suburb}
                      </strong>
                      <span className={`badge ${job.state}`}>{label(job.state)}</span>
                    </div>
                    <div className="muted">
                      {request.contact_name} · {when(job.created_at)} · <span className="mono">{shortId(job.job_id)}</span>
                    </div>
                  </li>
                ))}
              </ul>
            </>
          )}
        </aside>

        <section>
          {creating ? (
            <RequestForm
              role={user.role}
              onSubmit={(body) =>
                run(async () => {
                  const request = await client.logRequest(body);
                  setCreating(false);
                  setSelected(request.request_id);
                })
              }
            />
          ) : selected && tab === "jobs" ? (
            <JobDetail key={`${selected}-${user.id}`} user={user} jobId={selected} />
          ) : selected ? (
            <RequestDetail
              key={`${selected}-${user.id}`}
              user={user}
              requestId={selected}
              run={run}
              onAccepted={(jobId) => showTab("jobs", jobId)}
            />
          ) : (
            <div className="card muted">{tab === "jobs" ? "Select a job." : "Select a request, or create a new one."}</div>
          )}
        </section>
      </main>
    </>
  );
}
