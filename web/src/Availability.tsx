import { useCallback, useState } from "react";
import { api, type AvailabilitySlot, type User } from "./api";
import { iso, local, windowOf } from "./format";
import { usePolled } from "./usePolled";

type Run = (action: () => Promise<unknown>) => Promise<boolean>;

// a driver's own availability (Task 8). Slots are never edited: remove one and declare it again
export function Availability({ user, run }: { user: User; run: Run }) {
  const load = useCallback(() => api(user).listSlots(), [user]);
  const [slots, refresh] = usePolled<AvailabilitySlot[]>(load);
  const [times, setTimes] = useState(() => [local(1), local(9)]);
  const act = (action: () => Promise<unknown>) => run(action).then((ok) => (refresh(), ok));

  function declare(e: React.FormEvent) {
    e.preventDefault();
    act(() => api(user).declareSlot([iso(times[0]), iso(times[1])]));
  }

  return (
    <div className="detail">
      <form className="card" onSubmit={declare}>
        <h3>Declare availability</h3>
        <p className="muted">Office staff can allocate you a job when one of your slots covers its whole pickup window.</p>
        <div className="row">
          <input type="datetime-local" value={times[0]} onChange={(e) => setTimes([e.target.value, times[1]])} />
          <input type="datetime-local" value={times[1]} onChange={(e) => setTimes([times[0], e.target.value])} />
        </div>
        <button type="submit" className="primary">
          Add slot
        </button>
      </form>

      <div className="card">
        <h3>Your slots</h3>
        {slots?.length === 0 && <p className="muted">No slots yet, so you won't be offered any jobs.</p>}
        {slots?.map((slot) => (
          <div key={slot.id} className="quote title">
            <span>{windowOf(slot.window)}</span>
            <button className="danger" onClick={() => act(() => api(user).removeSlot(slot.id))}>
              Remove
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
