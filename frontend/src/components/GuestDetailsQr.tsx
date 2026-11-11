import { useQuery } from "@tanstack/react-query";
import { Copy, Share2 } from "lucide-react";
import { useState } from "react";
import { api } from "../api/client";
import { QrCode } from "./QrCode";

/** QR code the party scans so every guest adds their own details and waiver.
 *  `linkPath` is the POST endpoint that issues the guest-details link. */
export function GuestDetailsQr({ linkPath, reference }: { linkPath: string; reference: string }) {
  const link = useQuery({
    queryKey: ["guest-details-link", linkPath],
    queryFn: () => api<{ url: string }>(linkPath, { method: "POST" }),
    staleTime: Infinity,
    retry: 1,
  });
  const [copied, setCopied] = useState(false);
  if (link.isLoading) return <div className="loading">Preparing the guest QR code…</div>;
  if (link.error || !link.data) return <div className="error-banner">The guest QR code couldn't be created. The customer can still add guests from their confirmation email.</div>;
  const url = link.data.url;
  const copy = async () => { await navigator.clipboard?.writeText(url); setCopied(true); };
  const share = async () => {
    if (navigator.share) { try { await navigator.share({ title: "Add your guest details", url }); return; } catch { /* closed */ } }
    await copy();
  };
  return <section className="guest-qr">
    <h2>Add every guest's details</h2>
    <p className="muted-note">The customer scans this code, then each guest in the party fills in their own name, date of birth, phone, email and waiver.</p>
    <QrCode value={url} label={`QR code for booking ${reference} guest details`} />
    <div className="toolbar" style={{ justifyContent: "center", flexWrap: "wrap" }}>
      <button type="button" className="button secondary" onClick={share}><Share2 size={15} />Share link</button>
      <button type="button" className="button secondary" onClick={copy}><Copy size={15} />{copied ? "Copied" : "Copy link"}</button>
    </div>
  </section>;
}
