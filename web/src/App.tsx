import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError, type DeliveryRequest, type RequestStatus, type Role, type User } from "./api";
import { label, shortId, when } from "./format";
import { RequestDetail } from "./RequestDetail";
import { RequestForm } from "./RequestForm";
import { usePolled } from "./usePolled";

// no login yet: pick who to act as (kept across reloads)
function useActingAs(): [User, (user: User) => void] {
  const [user, setUser] = useState<User>(() => JSON.parse(localStorage.getItem("user") ?? "null") ?? { id: "cust-1", role: "customer" });
  useEffect(() => localStorage.setItem("user", JSON.stringify(user)), [user]);
  return [user, setUser];
}

const ERROR_HINTS: Record<number, string> = { 409: "Someone else changed this first. It has been reloaded; try again." };

export default function App() {
  const [user, setUser] = useActingAs();
  const [idDraft, setIdDraft] = useState(user.id);
  const [status, setStatus] = useState<RequestStatus | undefined>(user.role === "staff" ? "open" : undefined);
  const [selected, setSelected] = useState<string>();
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string>();

  const client = useMemo(() => api(user), [user]);
  const load = useCallback(() => client.listRequests(status), [client, status]);
  const [requests, refresh] = usePolled<DeliveryRequest[]>(load);

  function switchTo(next: User) {
    setUser(next);
    setIdDraft(next.id);
    setSelected(undefined);
    setStatus(next.role === "staff" ? "open" : undefined);
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
          <button className="primary wide" onClick={() => (setCreating(true), setSelected(undefined))}>
            + New request
          </button>
          <nav className="filters">
            {([undefined, "open", "accepted", "cancelled"] as const).map((s) => (
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
          ) : selected ? (
            <RequestDetail key={`${selected}-${user.id}`} user={user} requestId={selected} run={run} />
          ) : (
            <div className="card muted">Select a request, or create a new one.</div>
          )}
        </section>
      </main>
    </>
  );
}
