const STORAGE_KEY = "passport-partner";

/** Hotel partner code from a partner booking link (`?partner=sunseeker`).
 *  Kept for the browser tab so it survives moving from the activity list to
 *  checkout; an unknown code simply books as Direct on the server. */
export function partnerFromLink(search: string): string | null {
  const code = new URLSearchParams(search).get("partner")?.trim() || null;
  try {
    if (code) sessionStorage.setItem(STORAGE_KEY, code);
    return code || sessionStorage.getItem(STORAGE_KEY);
  } catch {
    return code;
  }
}
