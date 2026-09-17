import { useState } from "react";
import { AlertTriangle } from "lucide-react";
import { Modal } from "./Modal";

export function DestructiveConfirmationDialog({ open, onOpenChange, itemName, consequences, onConfirm, busy }: { open: boolean; onOpenChange: (open: boolean) => void; itemName: string; consequences: string; onConfirm: () => void; busy?: boolean }) {
  const [value, setValue] = useState("");
  return <Modal open={open} onOpenChange={(next) => { setValue(""); onOpenChange(next); }} title={`Delete “${itemName}”?`} description="This action removes the item from active use."><div className="warning-box"><AlertTriangle size={18} /><p>{consequences}</p></div><label className="field"><span>Type <strong>DELETE</strong> to continue</span><input autoComplete="off" value={value} onChange={(event) => setValue(event.target.value)} /></label><div className="dialog-actions"><button className="button secondary" onClick={() => onOpenChange(false)}>Cancel</button><button className="button danger" disabled={value !== "DELETE" || busy} onClick={onConfirm}>{busy ? "Deleting…" : "Delete"}</button></div></Modal>;
}
