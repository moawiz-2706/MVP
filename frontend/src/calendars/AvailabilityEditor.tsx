import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Send, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { api, json } from "../api/client";
import type { Calendar, CalendarDateHour, CalendarHour, PushedSlot } from "../api/types";
import { useSession } from "../auth/GHLSessionProvider";
import { EmptyState } from "../components/EmptyState";
import { WeeklyHoursFields, hhmm, type WeeklyInterval } from "../components/WeeklyHoursFields";
import { formatDay, formatTime, isoDayInZone, zoneLabel } from "../lib/datetime";

const todayISO = () => new Date().toISOString().slice(0, 10);

type Mode = "day_wise" | "date_wise" | "pushed";
const modeLabels: Record<Mode, string> = { day_wise: "Day-wise", date_wise: "Date-wise", pushed: "Push availability" };

interface TimeInterval { start_time: string; end_time: string }
interface DateRangeHours { start_date: string; end_date: string; intervals: TimeInterval[] }

/** Group flat (date range, interval) rows into one entry per date range. */
function groupDateHours(rows: CalendarDateHour[]): DateRangeHours[] {
  const groups = new Map<string, DateRangeHours>();
  for (const row of rows) {
    const key = `${row.start_date}|${row.end_date}`;
    let group = groups.get(key);
    if (!group) {
      group = { start_date: row.start_date, end_date: row.end_date, intervals: [] };
      groups.set(key, group);
    }
    group.intervals.push({ start_time: hhmm(row.start_time), end_time: hhmm(row.end_time) });
  }
  return [...groups.values()];
}

type ModeProps = { calendar: Calendar; onCalendarChange: (calendar: Calendar) => void };

/**
 * Availability is governed by exactly one mode. Each tab keeps its own saved
 * rows, but only the active mode is consulted by the availability engine —
 * saving a tab (or pushing a time) makes that tab the active mode.
 */
export function AvailabilityEditor({ calendar, onCalendarChange }: ModeProps) {
  const active = activeMode(calendar);
  const [tab, setTab] = useState<Mode>(active);
  return (
    <>
      <div className="tabs">
        {(Object.keys(modeLabels) as Mode[]).map((mode) => (
          <button key={mode} className={`tab ${tab === mode ? "active" : ""}`} onClick={() => setTab(mode)}>{modeLabels[mode]}</button>
        ))}
      </div>
      <p style={{ fontSize: 12, color: "#697386", marginTop: 10 }}>
        Only one mode controls availability. <strong>{modeLabels[active]}</strong> is currently active — saving another tab switches to it.
      </p>
      {tab === "day_wise" && <DayWiseEditor calendar={calendar} onCalendarChange={onCalendarChange} />}
      {tab === "date_wise" && <DateWiseEditor calendar={calendar} onCalendarChange={onCalendarChange} />}
      {tab === "pushed" && <PushEditor calendar={calendar} onCalendarChange={onCalendarChange} />}
    </>
  );
}

function DayWiseEditor({ calendar, onCalendarChange }: ModeProps) {
  const client = useQueryClient();
  const query = useQuery({ queryKey: ["hours", calendar.id], queryFn: () => api<CalendarHour[]>(`/calendars/${calendar.id}/hours`) });
  const [hours, setHours] = useState<WeeklyInterval[]>([]);
  useEffect(() => {
    if (query.data) setHours(query.data.map(({ day_of_week, start_time, end_time }) => ({ day_of_week, start_time: hhmm(start_time), end_time: hhmm(end_time) })));
  }, [query.data]);

  const save = useMutation({
    mutationFn: async () => {
      const result = await api<CalendarHour[]>(`/calendars/${calendar.id}/hours`, json("PUT", { hours }));
      if (calendar.availability_mode !== "day_wise") {
        onCalendarChange(await api<Calendar>(`/calendars/${calendar.id}`, json("PATCH", { availability_mode: "day_wise" })));
      }
      return result;
    },
    onSuccess: (result) => {
      setHours(result.map((h) => ({ day_of_week: h.day_of_week, start_time: hhmm(h.start_time), end_time: hhmm(h.end_time) })));
      void client.invalidateQueries({ queryKey: ["hours", calendar.id] });
      void client.invalidateQueries({ queryKey: ["calendars"] });
    },
  });

  return (
    <div>
      <p style={{ fontSize: 12, color: "#697386" }}>Bookings must fit completely inside one interval. Add multiple intervals for split operating days.</p>
      <WeeklyHoursFields hours={hours} onChange={setHours} />
      {save.error && <div className="error-banner">{save.error.message}</div>}
      <div className="dialog-actions"><button className="button" disabled={save.isPending} onClick={() => save.mutate()}>{save.isPending ? "Saving…" : "Save day-wise hours"}</button></div>
    </div>
  );
}

function DateWiseEditor({ calendar, onCalendarChange }: ModeProps) {
  const client = useQueryClient();
  const query = useQuery({ queryKey: ["date-hours", calendar.id], queryFn: () => api<CalendarDateHour[]>(`/calendars/${calendar.id}/date-hours`) });
  const [ranges, setRanges] = useState<DateRangeHours[]>([]);
  useEffect(() => { if (query.data) setRanges(groupDateHours(query.data)); }, [query.data]);

  const update = (index: number, patch: Partial<DateRangeHours>) =>
    setRanges(ranges.map((range, i) => (i === index ? { ...range, ...patch } : range)));
  const updateInterval = (rangeIndex: number, intervalIndex: number, patch: Partial<TimeInterval>) =>
    update(rangeIndex, { intervals: ranges[rangeIndex]!.intervals.map((iv, i) => (i === intervalIndex ? { ...iv, ...patch } : iv)) });

  const save = useMutation({
    mutationFn: async () => {
      const hours = ranges.flatMap((range) =>
        range.intervals.map((interval) => ({ start_date: range.start_date, end_date: range.end_date, start_time: interval.start_time, end_time: interval.end_time })),
      );
      const result = await api<CalendarDateHour[]>(`/calendars/${calendar.id}/date-hours`, json("PUT", { hours }));
      if (calendar.availability_mode !== "date_wise") {
        onCalendarChange(await api<Calendar>(`/calendars/${calendar.id}`, json("PATCH", { availability_mode: "date_wise" })));
      }
      return result;
    },
    onSuccess: (result) => {
      setRanges(groupDateHours(result));
      void client.invalidateQueries({ queryKey: ["date-hours", calendar.id] });
      void client.invalidateQueries({ queryKey: ["calendars"] });
    },
  });

  return (
    <div>
      <p style={{ fontSize: 12, color: "#697386" }}>Availability applies only on these date ranges. Each range has its own opening intervals, and a booking must fit completely inside one of them.</p>
      {ranges.map((range, rangeIndex) => (
        <div key={rangeIndex} style={{ borderTop: "1px solid #eef0f2", padding: "13px 0", display: "grid", gap: 9 }}>
          <div className="toolbar">
            <label className="field" style={{ margin: 0 }}><span>From date</span>
              <input className="control" type="date" value={range.start_date} onChange={(e) => update(rangeIndex, { start_date: e.target.value })} />
            </label>
            <label className="field" style={{ margin: 0 }}><span>To date</span>
              <input className="control" type="date" value={range.end_date} min={range.start_date} onChange={(e) => update(rangeIndex, { end_date: e.target.value })} />
            </label>
            <button className="icon-button" title="Remove date range" onClick={() => setRanges(ranges.filter((_, i) => i !== rangeIndex))}><Trash2 size={14} /></button>
          </div>
          <div style={{ display: "grid", gap: 7, paddingLeft: 12 }}>
            {range.intervals.map((interval, intervalIndex) => (
              <div className="toolbar" key={intervalIndex}>
                <input className="control" type="time" style={{ maxWidth: 125 }} value={interval.start_time} onChange={(e) => updateInterval(rangeIndex, intervalIndex, { start_time: e.target.value })} />
                <span style={{ fontSize: 11, color: "#7b8492" }}>to</span>
                <input className="control" type="time" style={{ maxWidth: 125 }} value={interval.end_time} onChange={(e) => updateInterval(rangeIndex, intervalIndex, { end_time: e.target.value })} />
                <button className="icon-button" onClick={() => update(rangeIndex, { intervals: range.intervals.filter((_, i) => i !== intervalIndex) })}><Trash2 size={14} /></button>
              </div>
            ))}
            <button className="button ghost small" style={{ justifySelf: "start" }} onClick={() => update(rangeIndex, { intervals: [...range.intervals, { start_time: "08:00", end_time: "18:00" }] })}><Plus size={14} />Add interval</button>
          </div>
        </div>
      ))}
      {!ranges.length && <EmptyState title="No date ranges" copy="Add a date range to open this calendar for booking." />}
      <button className="button ghost small" style={{ marginTop: 12 }} onClick={() => setRanges([...ranges, { start_date: todayISO(), end_date: todayISO(), intervals: [{ start_time: "08:00", end_time: "18:00" }] }])}><Plus size={14} />Add date range</button>
      {save.error && <div className="error-banner" style={{ marginTop: 12 }}>{save.error.message}</div>}
      <div className="dialog-actions"><button className="button" disabled={save.isPending} onClick={() => save.mutate()}>{save.isPending ? "Saving…" : "Save date-wise hours"}</button></div>
    </div>
  );
}

/** Wall-clock end of a start time plus a duration, e.g. "13:30" or "01:00 (+1 day)". */
function endPreview(start: string, minutes: number): string {
  const [h = 0, m = 0] = start.split(":").map(Number);
  const total = h * 60 + m + minutes;
  const days = Math.floor(total / 1440);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(Math.floor((total % 1440) / 60))}:${pad(total % 60)}${days ? ` (+${days} day${days > 1 ? "s" : ""})` : ""}`;
}

/**
 * Push availability: only start times the operator pushes are bookable. The end
 * is start + the calendar's duration, and the slot interval does not apply.
 */
function PushEditor({ calendar, onCalendarChange }: ModeProps) {
  const client = useQueryClient();
  const { me } = useSession();
  const tz = me.operator.time_zone;
  const query = useQuery({ queryKey: ["pushed-slots", calendar.id], queryFn: () => api<PushedSlot[]>(`/calendars/${calendar.id}/pushed-slots`) });
  const [day, setDay] = useState(() => isoDayInZone(new Date(), tz));
  const [time, setTime] = useState("09:00");
  const isActive = calendar.availability_mode === "pushed";
  const refresh = () => Promise.all([client.invalidateQueries({ queryKey: ["calendars"] }), client.invalidateQueries({ queryKey: ["bookings"] })]);
  const activate = async () => { if (!isActive) onCalendarChange(await api<Calendar>(`/calendars/${calendar.id}`, json("PATCH", { availability_mode: "pushed" }))); };

  const push = useMutation({
    mutationFn: async () => {
      const result = await api<PushedSlot[]>(`/calendars/${calendar.id}/pushed-slots`, json("POST", { slots: [{ day, start_time: time }] }));
      await activate();
      return result;
    },
    onSuccess: (result) => { client.setQueryData(["pushed-slots", calendar.id], result); void refresh(); },
  });
  const switchMode = useMutation({ mutationFn: activate, onSuccess: () => void refresh() });
  const remove = useMutation({
    mutationFn: (id: string) => api<void>(`/calendars/${calendar.id}/pushed-slots/${id}`, { method: "DELETE" }),
    onSuccess: () => { void client.invalidateQueries({ queryKey: ["pushed-slots", calendar.id] }); void refresh(); },
  });
  const error = push.error || remove.error || switchMode.error;

  return (
    <div>
      <p style={{ fontSize: 12, color: "#697386" }}>Only the start times you push are offered. Each ends {calendar.duration_minutes} minutes later (the calendar's duration); the slot interval is not used. Resources and blocked dates apply as usual. Times are in {zoneLabel(tz)}.</p>
      {!isActive && (
        <div className="warning-box"><p>Pushing a time switches this calendar to push availability, so its {modeLabels[activeMode(calendar)]} hours stop applying until you save that tab again.{query.data?.length ? <> <button className="button secondary small" style={{ marginLeft: 6 }} disabled={switchMode.isPending} onClick={() => switchMode.mutate()}>Use pushed times now</button></> : null}</p></div>
      )}
      <form className="toolbar" style={{ alignItems: "flex-end", paddingBottom: 14 }} onSubmit={(e) => { e.preventDefault(); push.mutate(); }}>
        <label className="field" style={{ margin: 0 }}><span>Date</span><input className="control" type="date" required min={isoDayInZone(new Date(), tz)} value={day} onChange={(e) => setDay(e.target.value)} /></label>
        <label className="field" style={{ margin: 0 }}><span>Start time</span><input className="control" type="time" required value={time} onChange={(e) => setTime(e.target.value)} /></label>
        <div className="field" style={{ margin: 0 }}><span>Ends</span><div className="control" style={{ background: "#f8f9fa", minWidth: 110 }}>{time ? endPreview(time, calendar.duration_minutes) : "—"}</div></div>
        <button className="button" disabled={push.isPending || !day || !time}><Send size={14} />{push.isPending ? "Pushing…" : "Push availability"}</button>
      </form>
      {error && <div className="error-banner">{error.message}</div>}
      <div className="detail-section" style={{ marginTop: 6 }}>
        <h3>Upcoming pushed times</h3>
        {query.isLoading ? <div className="loading">Loading…</div> : !query.data?.length ? <EmptyState title="Nothing pushed yet" copy="Push a date and start time to open it for booking." /> : query.data.map((slot) => (
          <div className="list-row" key={slot.id}>
            <span><strong>{formatDay(slot.start_at, tz)}</strong> · {formatTime(slot.start_at, tz)} – {formatTime(slot.end_at, tz)}</span>
            <button className="icon-button" aria-label="Remove pushed time" disabled={remove.isPending} onClick={() => remove.mutate(slot.id)}><Trash2 size={14} /></button>
          </div>
        ))}
        {!!query.data?.length && <p className="muted-note">Removing a time stops new bookings for it; existing bookings are kept.</p>}
      </div>
    </div>
  );
}

function activeMode(calendar: Calendar): Mode {
  return (calendar.availability_mode in modeLabels ? calendar.availability_mode : "day_wise") as Mode;
}
