import { useSearchParams } from "react-router-dom";

/**
 * `?embed=1` is application-level public-booking state. Once a customer enters
 * embedded mode it must survive every internal navigation (operator -> category
 * -> calendar -> checkout -> confirmation) so the flow never breaks out of the
 * host iframe.
 */
export function useEmbed(): boolean {
  const [params] = useSearchParams();
  return params.get("embed") === "1";
}

/** Append `?embed=1` (or `&embed=1`) to an internal booking path when embedded. */
export function withEmbed(path: string, embed: boolean): string {
  if (!embed) return path;
  return `${path}${path.includes("?") ? "&" : "?"}embed=1`;
}
