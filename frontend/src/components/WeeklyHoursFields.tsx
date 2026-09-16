import { Plus, Trash2 } from "lucide-react";

export interface WeeklyInterval { day_of_week: number; start_time: string; end_time: string }

export const weekdays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
export const hhmm = (value: string) => value.slice(0, 5);

/** Per-weekday interval editor; several intervals on a day give a split schedule. */
export function WeeklyHoursFields({ hours, onChange }: { hours: WeeklyInterval[]; onChange: (hours: WeeklyInterval[]) => void }) {
  const patch = (index: number, change: Partial<WeeklyInterval>) => onChange(hours.map((h, i) => (i === index ? { ...h, ...change } : h)));
  return (
    <>
      {weekdays.map((day, dayIndex) => (
        <div key={day} style={{ borderTop: "1px solid #eef0f2", padding: "11px 0", display: "grid", gridTemplateColumns: "100px 1fr", gap: 10 }}>
          <strong style={{ fontSize: 12, paddingTop: 8 }}>{day}</strong>
          <div style={{ display: "grid", gap: 7 }}>
            {hours.map((hour, index) => hour.day_of_week !== dayIndex ? null : (
              <div className="toolbar" key={index}>
                <input className="control" type="time" required style={{ maxWidth: 125 }} value={hour.start_time} onChange={(e) => patch(index, { start_time: e.target.value })} />
                <span style={{ fontSize: 11, color: "#7b8492" }}>to</span>
                <input className="control" type="time" required style={{ maxWidth: 125 }} value={hour.end_time} onChange={(e) => patch(index, { end_time: e.target.value })} />
                <button type="button" className="icon-button" aria-label={`Remove ${day} interval`} onClick={() => onChange(hours.filter((_, i) => i !== index))}><Trash2 size={14} /></button>
              </div>
            ))}
            <button type="button" className="button ghost small" style={{ justifySelf: "start" }} onClick={() => onChange([...hours, { day_of_week: dayIndex, start_time: "08:00", end_time: "18:00" }])}><Plus size={14} />Add interval</button>
          </div>
        </div>
      ))}
    </>
  );
}
