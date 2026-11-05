import QRCode from "qrcode";
import { useEffect, useState } from "react";

/** A scannable QR code for a link, drawn as an SVG image. */
export function QrCode({ value, size = 220, label }: { value: string; size?: number; label: string }) {
  const [src, setSrc] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    QRCode.toString(value, { type: "svg", errorCorrectionLevel: "M", margin: 2 })
      .then((svg) => { if (live) setSrc(`data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`); })
      .catch(() => { if (live) setSrc(null); });
    return () => { live = false; };
  }, [value]);
  if (!src) return <div className="qr-code qr-placeholder" style={{ width: size, height: size }} aria-busy="true" />;
  return <img className="qr-code" src={src} width={size} height={size} alt={label} />;
}
