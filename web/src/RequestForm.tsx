import { useState } from "react";
import type { NewRequest, ParcelSize, Role } from "./api";

const EMPTY = {
  customer_id: "",
  contact_name: "",
  contact_phone: "",
  parcels: [{ size: "small" as ParcelSize, weight_kg: "", quantity: "1" }],
  pickup: { street: "", suburb: "", postcode: "" },
  dropoff: { street: "", suburb: "", postcode: "" },
};

export function RequestForm({ role, onSubmit }: { role: Role; onSubmit: (body: NewRequest) => Promise<boolean> }) {
  const [form, setForm] = useState(EMPTY);
  const set = (field: string, value: string) => setForm({ ...form, [field]: value });
  const setAddress = (which: "pickup" | "dropoff", field: string, value: string) =>
    setForm({ ...form, [which]: { ...form[which], [field]: value } });
  const setParcel = (i: number, field: string, value: string) =>
    setForm({ ...form, parcels: form.parcels.map((p, j) => (j === i ? { ...p, [field]: value } : p)) });
  const addParcel = () => setForm({ ...form, parcels: [...form.parcels, EMPTY.parcels[0]] });
  const removeParcel = (i: number) => setForm({ ...form, parcels: form.parcels.filter((_, j) => j !== i) });

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const ok = await onSubmit({
      // staff log for a caller: their account, or none for an anonymous request
      ...(role === "staff" ? { customer_id: form.customer_id || null } : {}),
      contact_name: form.contact_name,
      contact_phone: form.contact_phone,
      parcels: form.parcels.map((p) => ({ size: p.size, weight_kg: p.weight_kg, quantity: Number(p.quantity) })),
      pickup_address: form.pickup,
      dropoff_address: form.dropoff,
    });
    if (ok) setForm(EMPTY);
  }

  const address = (which: "pickup" | "dropoff") => (
    <fieldset>
      <legend>{which === "pickup" ? "Pickup" : "Drop-off"}</legend>
      <input placeholder="Street" value={form[which].street} onChange={(e) => setAddress(which, "street", e.target.value)} />
      <div className="row">
        <input placeholder="Suburb" value={form[which].suburb} onChange={(e) => setAddress(which, "suburb", e.target.value)} />
        <input placeholder="Postcode" value={form[which].postcode} onChange={(e) => setAddress(which, "postcode", e.target.value)} />
      </div>
    </fieldset>
  );

  return (
    <form className="card" onSubmit={submit}>
      <h2>{role === "staff" ? "Log a request for a caller" : "Request a delivery"}</h2>
      {role === "staff" && (
        <input placeholder="Caller's customer id (blank if anonymous)" value={form.customer_id} onChange={(e) => set("customer_id", e.target.value)} />
      )}
      <div className="row">
        <input placeholder="Contact name" value={form.contact_name} onChange={(e) => set("contact_name", e.target.value)} />
        <input placeholder="Contact phone" value={form.contact_phone} onChange={(e) => set("contact_phone", e.target.value)} />
      </div>
      <fieldset>
        <legend>Parcels</legend>
        {form.parcels.map((p, i) => (
          <div className="row" key={i}>
            <select value={p.size} onChange={(e) => setParcel(i, "size", e.target.value)}>
              <option value="small">Small</option>
              <option value="medium">Medium</option>
              <option value="large">Large</option>
            </select>
            <input placeholder="Weight (kg)" value={p.weight_kg} onChange={(e) => setParcel(i, "weight_kg", e.target.value)} />
            <input type="number" min="1" placeholder="Qty" value={p.quantity} onChange={(e) => setParcel(i, "quantity", e.target.value)} />
            {form.parcels.length > 1 && (
              <button type="button" className="remove" onClick={() => removeParcel(i)} aria-label="Remove parcel">×</button>
            )}
          </div>
        ))}
        <button type="button" onClick={addParcel}>+ Add parcel</button>
      </fieldset>
      {address("pickup")}
      {address("dropoff")}
      <button type="submit" className="primary">Submit request</button>
    </form>
  );
}
