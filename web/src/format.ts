export const when = (iso: string) =>
  new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

export const windowOf = ([start, end]: [string, string]) => `${when(start)} – ${new Date(end).toLocaleTimeString(undefined, { timeStyle: "short" })}`;

export const label = (value: string) => value.replace(/_/g, " ");

export const shortId = (id: string) => id.slice(0, 8);
