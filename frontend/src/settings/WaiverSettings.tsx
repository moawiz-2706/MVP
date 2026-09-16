import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type ChangeEvent, type FormEvent } from "react";
import { api, json } from "../api/client";
import type { WaiverSettingsData } from "../api/types";

type Form = Record<keyof WaiverSettingsData, string>;
const EMPTY: Form = { waiver_title: "", waiver_website: "", waiver_text: "", waiver_opt_in_label: "" };

export function WaiverSettings() {
  const client = useQueryClient();
  const query = useQuery({ queryKey: ["waiver-settings"], queryFn: () => api<WaiverSettingsData>("/settings/waiver") });
  const [form, setForm] = useState<Form>(EMPTY);
  useEffect(() => {
    if (query.data) setForm({
      waiver_title: query.data.waiver_title ?? "",
      waiver_website: query.data.waiver_website ?? "",
      waiver_text: query.data.waiver_text ?? "",
      waiver_opt_in_label: query.data.waiver_opt_in_label ?? "",
    });
  }, [query.data]);
  const save = useMutation({
    mutationFn: () => api<WaiverSettingsData>("/settings/waiver", json("PUT", form)),
    onSuccess: (result) => client.setQueryData(["waiver-settings"], result),
  });
  const set = (key: keyof Form) => (event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => { save.reset(); setForm({ ...form, [key]: event.target.value }); };
  const submit = (event: FormEvent) => { event.preventDefault(); save.mutate(); };

  return (
    <>
      <h2>Waiver</h2>
      <p>Every confirmed booking gets a waiver link in its confirmation email, on the booking confirmation page, and in its reminders until it is signed. The form asks for one person per ticket booked, and one signature covers everyone.</p>
      {query.isLoading ? <div className="loading">Loading…</div> : (
        <form onSubmit={submit}>
          <div className="form-grid">
            <label className="field full"><span>Title</span><input value={form.waiver_title} onChange={set("waiver_title")} maxLength={200} placeholder="Punta Gorda Adventures LLC. Waiver" /></label>
            <label className="field"><span>Company website</span><input value={form.waiver_website} onChange={set("waiver_website")} maxLength={300} placeholder="https://puntagordaadventures.com" /></label>
            <label className="field"><span>Opt-in checkbox (optional)</span><input value={form.waiver_opt_in_label} onChange={set("waiver_opt_in_label")} maxLength={200} placeholder="I'm adventurous and would love to go on more adventures" /></label>
            <label className="field full"><span>Waiver text</span><textarea rows={16} value={form.waiver_text} onChange={set("waiver_text")} /></label>
          </div>
          <p className="muted-note">Leave a blank line between paragraphs. Wrap a heading or paragraph in ## to make it bold, like ##ACKNOWLEDGEMENT OF RISKS##. Leave the text empty to stop sending waivers. Changes apply to waivers not yet signed; signed waivers keep the exact text that was signed.</p>
          {save.error && <div className="error-banner" style={{ marginTop: 12 }}>{save.error.message}</div>}
          <div className="dialog-actions">
            {save.isSuccess && <span className="muted-note" style={{ alignSelf: "center" }}>Saved</span>}
            <button className="button" disabled={save.isPending}>{save.isPending ? "Saving…" : "Save waiver"}</button>
          </div>
        </form>
      )}
    </>
  );
}
