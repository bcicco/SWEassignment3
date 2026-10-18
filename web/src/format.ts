export const when = (iso: string) =>
  new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

export const windowOf = ([start, end]: [string, string]) => `${when(start)} – ${new Date(end).toLocaleTimeString(undefined, { timeStyle: "short" })}`;

export const label = (value: string) => value.replace(/_/g, " ");

export const shortId = (id: string) => id.slice(0, 8);

// a datetime-local input's value `hours` from now, on the hour
export const local = (hours: number) => {
  const d = new Date(Date.now() + hours * 3600e3);
  d.setMinutes(0, 0, 0);
  return new Date(d.getTime() - d.getTimezoneOffset() * 60e3).toISOString().slice(0, 16);
};

// a datetime-local input's value as an ISO timestamp for the API
export const iso = (value: string) => new Date(value).toISOString();
