import { ImagePlus, Link2, Loader2, Trash2, Upload } from "lucide-react";
import { useRef, useState } from "react";
import { api, json } from "../api/client";
import { videoSource } from "../lib/video";

type Kind = "image" | "video";
interface Stored { url: string }

const ACCEPT: Record<Kind, string> = {
  image: "image/jpeg,image/png,image/webp,image/gif",
  video: "video/mp4,video/webm,video/quicktime",
};

/** Upload a file, or copy a public link, into HighLevel Media Storage. */
function useMediaStore() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = async (task: () => Promise<Stored>): Promise<string | null> => {
    setBusy(true); setError(null);
    try { return (await task()).url; } catch (failure) { setError(failure instanceof Error ? failure.message : "Upload failed"); return null; } finally { setBusy(false); }
  };
  const upload = (file: File) => {
    const body = new FormData();
    body.append("file", file);
    return run(() => api<Stored>("/media/upload", { method: "POST", body }));
  };
  const copy = (url: string) => run(() => api<Stored>("/media/import", json("POST", { url })));
  return { busy, error, upload, copy };
}

function AddMedia({ kind, onAdded, label }: { kind: Kind; onAdded: (url: string) => void; label: string }) {
  const store = useMediaStore();
  const input = useRef<HTMLInputElement>(null);
  const [link, setLink] = useState("");
  const addLink = async () => {
    // Several image links can be pasted at once (one per line or space-separated).
    const values = link.split(/\s+/).map((value) => value.trim()).filter(Boolean);
    if (!values.length) return;
    const left: string[] = [];
    for (const value of kind === "video" ? values.slice(0, 1) : values) {
      // YouTube and Vimeo stay as links; anything else is copied into HighLevel.
      const embed = kind === "video" && videoSource(value)?.kind === "embed";
      const url = embed ? value : await store.copy(value);
      if (url) onAdded(url); else left.push(value);
    }
    setLink(left.join(" "));
  };
  return <div className="media-add">
    <div className="media-add-row">
      <button type="button" className="button secondary" disabled={store.busy} onClick={() => input.current?.click()}>
        {store.busy ? <Loader2 size={15} className="spin" /> : <Upload size={15} />}{label}
      </button>
      <input ref={input} type="file" hidden accept={ACCEPT[kind]} multiple={kind === "image"} onChange={async (event) => {
        const files = Array.from(event.target.files || []);
        event.target.value = "";
        for (const file of files) { const url = await store.upload(file); if (url) onAdded(url); }
      }} />
      <div className="media-link">
        <Link2 size={15} />
        <input type="text" inputMode="url" placeholder={kind === "video" ? "YouTube, Vimeo or video link" : "Paste image links (several at once is fine)"} value={link} onChange={(event) => setLink(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); void addLink(); } }} />
        <button type="button" className="button secondary" disabled={store.busy || !link.trim()} onClick={() => void addLink()}>Add</button>
      </div>
    </div>
    {store.error && <div className="error-banner">{store.error}</div>}
  </div>;
}

/** Hero photo plus gallery, stored in HighLevel; the first photo is the hero. */
export function PhotoPicker({ hero, gallery, onChange }: { hero: string; gallery: string[]; onChange: (hero: string, gallery: string[]) => void }) {
  const photos = [hero, ...gallery].filter(Boolean);
  const set = (next: string[]) => { latest.current = next; onChange(next[0] || "", next.slice(1, 13)); };
  // Uploads finish one after another; each adds to the newest list, not a stale one.
  const latest = useRef(photos);
  latest.current = photos;
  const setPhotos = (update: (current: string[]) => string[]) => set(update(latest.current));
  return <div className="field full">
    <span>Photos</span>
    {photos.length > 0 ? <div className="media-grid">
      {photos.map((url, index) => <figure key={`${url}-${index}`} className={index === 0 ? "media-tile hero" : "media-tile"}>
        <img src={url} alt="" loading="lazy" />
        {index === 0 && <figcaption>Main photo</figcaption>}
        <div className="media-tile-actions">
          {index > 0 && <button type="button" className="icon-button" title="Make main photo" aria-label="Make main photo" onClick={() => set([url, ...photos.filter((_, i) => i !== index)])}><ImagePlus size={14} /></button>}
          <button type="button" className="icon-button" title="Remove photo" aria-label="Remove photo" onClick={() => set(photos.filter((_, i) => i !== index))}><Trash2 size={14} /></button>
        </div>
      </figure>)}
    </div> : <p className="muted-note" style={{ margin: "4px 0" }}>No photos yet.</p>}
    {photos.length < 13 && <AddMedia kind="image" label="Upload photos" onAdded={(url) => setPhotos((current) => [...current, url])} />}
    <small>Photos are stored in your HighLevel Media Storage. The main photo appears on the booking pages; up to 12 more show in the gallery.</small>
  </div>;
}

export function VideoPicker({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  const source = videoSource(value);
  return <div className="field full">
    <span>Video</span>
    {value ? <div className="media-video">
      {source?.kind === "embed" ? <iframe src={source.src} title="Calendar video" allow="encrypted-media; picture-in-picture" allowFullScreen /> : source ? <video src={source.src} controls preload="metadata" /> : <div className="error-banner">This link can't be played. Use an https YouTube, Vimeo or video-file link.</div>}
      <button type="button" className="button secondary" onClick={() => onChange("")}><Trash2 size={15} />Remove video</button>
    </div> : <AddMedia kind="video" label="Upload video" onAdded={onChange} />}
    <small>Upload a short clip (up to 4 MB), or paste a YouTube or Vimeo link for longer videos.</small>
  </div>;
}
