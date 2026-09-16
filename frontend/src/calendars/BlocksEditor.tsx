import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { api, json } from "../api/client";
import type { Calendar, CalendarBlock } from "../api/types";
import { EmptyState } from "../components/EmptyState";

interface BlockRange { start_date: string; end_date: string; reason: string }

const todayISO = () => new Date().toISOString().slice(0, 10);

/**
 * Blocked dates are whole-day ranges. The backend converts them to timestamps in
 * the operator's timezone (and derives the dates back), so DST is handled there
 * rather than in the browser.
 */
export function BlocksEditor({ calendar }: { calendar: Calendar }) {
  const client = useQueryClient();
  const query = useQuery({ queryKey: ["blocks", calendar.id], queryFn: () => api<CalendarBlock[]>(`/calendars/${calendar.id}/blocks`) });
  const [ranges, setRanges] = useState<BlockRange[]>([]);
  useEffect(() => {
    if (query.data) setRanges(query.data.map((block) => ({ start_date: block.start_date, end_date: block.end_date, reason: block.reason ?? "" })));
  }, [query.data]);

  const update = (index: number, patch: Partial<BlockRange>) =>
    setRanges(ranges.map((range, i) => (i === index ? { ...range, ...patch } : range)));

  const save = useMutation({
    mutationFn: () => api<CalendarBlock[]>(`/calendars/${calendar.id}/blocks`, json("PUT", {
      blocks: ranges.map((range) => ({ start_date: range.start_date, end_date: range.end_date, reason: range.reason || null })),
    })),
    onSuccess: (result) => {
      setRanges(result.map((block) => ({ start_date: block.start_date, end_date: block.end_date, reason: block.reason ?? "" })));
      void client.invalidateQueries({ queryKey: ["blocks", calendar.id] });
    },
  });

  return (
    <div>
      <p style={{ fontSize: 12, color: "#697386" }}>Add date ranges when this calendar is closed. Both dates are inclusive, and blocked days are unavailable regardless of inventory.</p>
      {ranges.map((range, index) => (
        <div key={index} style={{ borderTop: "1px solid #eef0f2", padding: "13px 0" }}>
          <div className="toolbar">
            <label className="field" style={{ margin: 0 }}><span>From date</span>
              <input className="control" type="date" value={range.start_date} onChange={(e) => update(index, { start_date: e.target.value })} />
            </label>
            <label className="field" style={{ margin: 0 }}><span>To date</span>
              <input className="control" type="date" value={range.end_date} min={range.start_date} onChange={(e) => update(index, { end_date: e.target.value })} />
            </label>
            <label className="field" style={{ margin: 0, flex: 1 }}><span>Reason</span>
              <input className="control" value={range.reason} placeholder="Maintenance, weather closure…" onChange={(e) => update(index, { reason: e.target.value })} />
            </label>
            <button className="icon-button" title="Remove blocked range" onClick={() => setRanges(ranges.filter((_, i) => i !== index))}><Trash2 size={14} /></button>
          </div>
        </div>
      ))}
      {!ranges.length && <EmptyState title="No blocked dates" copy="This calendar currently follows its availability without exceptions." />}
      <button className="button ghost small" style={{ marginTop: 12 }} onClick={() => setRanges([...ranges, { start_date: todayISO(), end_date: todayISO(), reason: "" }])}><Plus size={14} />Add blocked range</button>
      {save.error && <div className="error-banner" style={{ marginTop: 12 }}>{save.error.message}</div>}
      <div className="dialog-actions"><button className="button" disabled={save.isPending} onClick={() => save.mutate()}>{save.isPending ? "Saving…" : "Save blocked dates"}</button></div>
    </div>
  );
}
