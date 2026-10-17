// typed client for the FastAPI backend (src/swe/api). Types mirror its OpenAPI schema
// at /docs; there's no login, so every call says who it's acting as

export type Role = "customer" | "staff";
export type User = { id: string; role: Role };

export type RequestStatus = "open" | "accepted" | "cancelled";
export type QuoteStatus = "pending" | "accepted" | "rejected" | "revision_requested" | "superseded";
export type ParcelSize = "small" | "medium" | "large";

export type Address = { street: string; suburb: string; postcode: string };
export type Parcel = { size: ParcelSize; weight_kg: string; quantity: number };

export type DeliveryRequest = {
  request_id: string;
  created_at: string;
  customer_id: string | null;
  logged_by: string | null;
  contact_name: string;
  contact_phone: string;
  parcels: Parcel[];
  pickup_address: Address;
  dropoff_address: Address;
  status: RequestStatus;
  current_quote_id: string | null;
};

export type Quote = {
  request_id: string;
  quote_id: string;
  price: string;
  eta_pickup: [string, string];
  eta_dropoff: [string, string];
  time_of_issue: string;
  expiry_time: string;
  issued_by: string;
  status: QuoteStatus;
  responded_by: string | null;
  responded_at: string | null;
};

// each event type adds its own fields (quote_id, price, ...)
export type HistoryEvent = {
  id: string;
  event_type: string;
  request_id: string;
  created_at: string;
  created_by: string | null;
  [field: string]: unknown;
};

export type RequestDetail = { request: DeliveryRequest; quotes: Quote[]; history: HistoryEvent[] };

export type NewRequest = {
  customer_id?: string | null;
  contact_name: string;
  contact_phone: string;
  parcels: Parcel[];
  pickup_address: Address;
  dropoff_address: Address;
};

export type NewQuote = { price: string; eta_pickup: [string, string]; eta_dropoff: [string, string] };

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

const BASE = import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8001";

async function call<T>(user: User, method: "GET" | "POST", path: string, body?: unknown): Promise<T> {
  const response = await fetch(BASE + path, {
    method,
    headers: { "X-User-Id": user.id, "X-User-Role": user.role, "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) {
    // 422s from FastAPI list each invalid field
    const detail = Array.isArray(data.detail)
      ? data.detail.map((d: { loc: string[]; msg: string }) => `${d.loc.slice(1).join(".")}: ${d.msg}`).join("; ")
      : data.detail;
    throw new ApiError(response.status, detail);
  }
  return data as T;
}

export const api = (user: User) => ({
  listRequests: (status?: RequestStatus) =>
    call<DeliveryRequest[]>(user, "GET", `/requests${status ? `?status=${status}` : ""}`),
  getRequest: (id: string) => call<RequestDetail>(user, "GET", `/requests/${id}`),
  logRequest: (body: NewRequest) => call<DeliveryRequest>(user, "POST", "/requests", body),
  cancel: (id: string) => call<DeliveryRequest>(user, "POST", `/requests/${id}/cancel`),
  issueQuote: (id: string, body: NewQuote) => call<Quote>(user, "POST", `/requests/${id}/quotes`, body),
  respond: (id: string, quoteId: string, action: "accept" | "reject" | "revision") =>
    call<unknown>(user, "POST", `/requests/${id}/quotes/${quoteId}/${action}`),
});
