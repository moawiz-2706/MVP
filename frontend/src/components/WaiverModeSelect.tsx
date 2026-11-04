export type WaiverMode = "party" | "per_guest";

/** Staff bookings only: one adult signs for the group, or every guest signs
 *  their own waiver. Customer and affiliate checkouts always use one. */
export function WaiverModeSelect({ value, onChange, guests }: { value: WaiverMode; onChange: (value: WaiverMode) => void; guests: number }) {
  if (guests < 2) return null;
  return <label className="field full"><span>Waivers</span><select value={value} onChange={(event) => onChange(event.target.value as WaiverMode)}>
    <option value="party">One waiver: one adult signs for all {guests} guests</option>
    <option value="per_guest">Separate waivers: a link for each of the {guests} guests</option>
  </select></label>;
}
