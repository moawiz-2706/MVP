/** How a calendar's video link is shown: an embedded player, or a plain <video>. */
export type VideoSource = { kind: "embed"; src: string } | { kind: "file"; src: string };

export function videoSource(url: string | null | undefined): VideoSource | null {
  if (!url) return null;
  let parsed: URL;
  try { parsed = new URL(url.trim()); } catch { return null; }
  if (parsed.protocol !== "https:") return null;
  const host = parsed.hostname.replace(/^www\.|^m\./, "");
  if (host === "youtu.be") {
    const id = parsed.pathname.slice(1).split("/")[0];
    return id ? { kind: "embed", src: `https://www.youtube-nocookie.com/embed/${encodeURIComponent(id)}` } : null;
  }
  if (host === "youtube.com" || host === "youtube-nocookie.com") {
    const id = parsed.searchParams.get("v") || parsed.pathname.match(/^\/(?:embed|shorts|live)\/([^/]+)/)?.[1];
    return id ? { kind: "embed", src: `https://www.youtube-nocookie.com/embed/${encodeURIComponent(id)}` } : null;
  }
  if (host === "vimeo.com" || host === "player.vimeo.com") {
    const id = parsed.pathname.match(/(\d{5,})/)?.[1];
    return id ? { kind: "embed", src: `https://player.vimeo.com/video/${id}` } : null;
  }
  return { kind: "file", src: parsed.toString() };
}
