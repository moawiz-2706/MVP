import { Plus, Trash2 } from "lucide-react";

export interface WeeklyInterval { day_of_week: number; start_time: string; end_time: string }

export const weekdays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
export const hhmm = (value: string) => value.slice(0, 5);

/** Per-weekday interval editor; several intervals on a day give a split schedule. */
export function WeeklyHoursFields({ hours, onChange }: { hours: WeeklyInterval[]; onChange: (hours: WeeklyInterval[]) => void }) {
  const patch = (index: number, change: Partial<WeeklyInterval>) => onChange(hours.map((hour, currentIndex) => (currentIndex === index ? { ...hour, ...change } : hour)));
  return (
    <>
      {weekdays.map((day, dayIndex) => (
        <div key={day} className="weekly-hours-day">
          <strong>{day}</strong>
          <div className="weekly-hours-intervals">
            {hours.map((hour, index) => hour.day_of_week !== dayIndex ? null : (
              <div className="weekly-hours-interval" key={index}>
                <input className="control" type="time" required value={hour.start_time} onChange={(event) => patch(index, { start_time: event.target.value })} />
                <span>to</span>
                <input className="control" type="time" required value={hour.end_time} onChange={(event) => patch(index, { end_time: event.target.value })} />
                <button type="button" className="icon-button" aria-label={`Remove ${day} interval`} onClick={() => onChange(hours.filter((_, currentIndex) => currentIndex !== index))}><Trash2 size={14} /></button>
              </div>
            ))}
            <button type="button" className="button ghost small" onClick={() => onChange([...hours, { day_of_week: dayIndex, start_time: "08:00", end_time: "18:00" }])}><Plus size={14} />Add interval</button>
          </div>
        </div>
      ))}
    </>
  );
}
