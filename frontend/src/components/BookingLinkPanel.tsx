import { useState } from "react";
import { Check, Copy, ExternalLink } from "lucide-react";

type EntityType = "operator" | "category" | "calendar";

function bookingBase(): string {
  // Public booking pages are served by this same frontend app, so its origin is
  // the correct base. VITE_PUBLIC_BOOKING_URL can override for split domains.
  const configured = import.meta.env.VITE_PUBLIC_BOOKING_URL as string | undefined;
  return (configured || window.location.origin).replace(/\/$/, "");
}

export function buildBookingPath(entityType: EntityType, operatorSlug: string, entitySlug?: string): string {
  if (entityType === "operator") return `/book/${operatorSlug}`;
  if (entityType === "category") return `/book/${operatorSlug}/category/${entitySlug}`;
  return `/book/${operatorSlug}/${entitySlug}`;
}

export function BookingLinkPanel({ entityType, operatorSlug, entitySlug, height = 850 }: { entityType: EntityType; operatorSlug: string; entitySlug?: string; height?: number }) {
  const [copied, setCopied] = useState<"link" | "embed" | null>(null);
  const path = buildBookingPath(entityType, operatorSlug, entitySlug);
  const publicUrl = `${bookingBase()}${path}`;
  const embedUrl = `${publicUrl}?embed=1`;
  const embedCode = `<iframe\n  src="${embedUrl}"\n  width="100%"\n  height="${height}"\n  style="border:0;"\n  loading="lazy"\n></iframe>`;

  const copy = (text: string, key: "link" | "embed") => {
    void navigator.clipboard?.writeText(text).then(
      () => { setCopied(key); window.setTimeout(() => setCopied(null), 1500); },
      () => setCopied(null),
    );
  };

  return <div className="booking-link-panel" style={{ marginTop: 18, paddingTop: 16, borderTop: "1px solid #e6e9e8" }}>
    <h3 style={{ fontSize: 13, margin: "0 0 10px" }}>Booking Page</h3>
    <label className="field"><span>Public booking link</span>
      <div className="toolbar" style={{ gap: 8 }}>
        <input className="control" readOnly value={publicUrl} onFocus={(e) => e.currentTarget.select()} style={{ flex: 1 }} />
        <button type="button" className="button secondary small" onClick={() => copy(publicUrl, "link")}>{copied === "link" ? <Check size={14} /> : <Copy size={14} />}Copy link</button>
        <button type="button" className="button ghost small" onClick={() => window.open(publicUrl, "_blank", "noopener")}><ExternalLink size={14} />Open</button>
      </div>
    </label>
    <label className="field" style={{ marginTop: 12 }}><span>Embed code</span>
      <textarea className="control" readOnly rows={6} value={embedCode} onFocus={(e) => e.currentTarget.select()} style={{ fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace", fontSize: 12 }} />
    </label>
    <div className="toolbar" style={{ marginTop: 8 }}>
      <button type="button" className="button secondary small" onClick={() => copy(embedCode, "embed")}>{copied === "embed" ? <Check size={14} /> : <Copy size={14} />}Copy embed code</button>
    </div>
  </div>;
}
