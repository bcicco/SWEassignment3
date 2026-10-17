import { useState } from "react";
import type { NewRequest, ParcelSize, Role } from "./api";

const EMPTY = {
  customer_id: "",
  contact_name: "",
  contact_phone: "",
  size: "small" as ParcelSize,
  weight_kg: "",
  quantity: "1",
  pickup: { street: "", suburb: "", postcode: "" },
  dropoff: { street: "", suburb: "", postcode: "" },
};

export function RequestForm({ role, onSubmit }: { role: Role; onSubmit: (body: NewRequest) => Promise<boolean> }) {
  const [form, setForm] = useState(EMPTY);
  const set = (field: string, value: string) => setForm({ ...form, [field]: value });
  const setAddress = (which: "pickup" | "dropoff", field: string, value: string) =>
    setForm({ ...form, [which]: { ...form[which], [field]: value } });

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const ok = await onSubmit({
      // staff log for a caller: their account, or none for an anonymous request
      ...(role === "staff" ? { customer_id: form.customer_id || null } : {}),
      contact_name: form.contact_name,
      contact_phone: form.contact_phone,
      parcels: [{ size: form.size, weight_kg: form.weight_kg, quantity: Number(form.quantity) }],
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
        <legend>Parcel</legend>
        <div className="row">
          <select value={form.size} onChange={(e) => set("size", e.target.value)}>
            <option value="small">Small</option>
            <option value="medium">Medium</option>
            <option value="large">Large</option>
          </select>
          <input placeholder="Weight (kg)" value={form.weight_kg} onChange={(e) => set("weight_kg", e.target.value)} />
          <input type="number" min="1" placeholder="Qty" value={form.quantity} onChange={(e) => set("quantity", e.target.value)} />
        </div>
      </fieldset>
      {address("pickup")}
      {address("dropoff")}
      <button type="submit" className="primary">Submit request</button>
    </form>
  );
}
