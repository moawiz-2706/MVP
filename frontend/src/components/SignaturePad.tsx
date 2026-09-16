import { useEffect, useRef, type PointerEvent } from "react";

/** Finger or mouse signature. Reports a PNG data URL after each stroke, or null when cleared. */
export function SignaturePad({ onChange }: { onChange: (dataUrl: string | null) => void }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const drawing = useRef(false);

  useEffect(() => {
    const canvas = canvasRef.current;
    const context = canvas?.getContext("2d");
    if (!canvas || !context) return;
    // Draw at device resolution so the signature stays crisp on phones.
    const ratio = window.devicePixelRatio || 1;
    const { width, height } = canvas.getBoundingClientRect();
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
    context.scale(ratio, ratio);
    context.lineWidth = 2.2;
    context.lineCap = "round";
    context.lineJoin = "round";
    context.strokeStyle = "#111827";
  }, []);

  const context = () => canvasRef.current?.getContext("2d") ?? null;
  const position = (event: PointerEvent<HTMLCanvasElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    return { x: event.clientX - rect.left, y: event.clientY - rect.top };
  };

  const start = (event: PointerEvent<HTMLCanvasElement>) => {
    const ctx = context();
    if (!ctx) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    drawing.current = true;
    const { x, y } = position(event);
    ctx.beginPath();
    ctx.moveTo(x, y);
    ctx.lineTo(x + 0.01, y + 0.01); // a tap still leaves a dot
    ctx.stroke();
  };
  const move = (event: PointerEvent<HTMLCanvasElement>) => {
    const ctx = context();
    if (!drawing.current || !ctx) return;
    const { x, y } = position(event);
    ctx.lineTo(x, y);
    ctx.stroke();
  };
  const end = () => {
    if (!drawing.current) return;
    drawing.current = false;
    onChange(canvasRef.current?.toDataURL("image/png") ?? null);
  };
  const clear = () => {
    const canvas = canvasRef.current;
    const ctx = context();
    if (canvas && ctx) {
      ctx.save();
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.restore();
    }
    onChange(null);
  };

  return (
    <div className="signature-pad">
      <canvas ref={canvasRef} aria-label="Signature area" onPointerDown={start} onPointerMove={move} onPointerUp={end} onPointerCancel={end} />
      <div className="signature-actions">
        <span>Sign above with your finger or mouse</span>
        <button type="button" className="button ghost small" onClick={clear}>Clear</button>
      </div>
    </div>
  );
}
