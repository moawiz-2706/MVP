import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState, type ChangeEvent, type FormEvent } from "react";
import { api, json } from "../api/client";
import type { MessageTemplate } from "../api/types";

interface MessageTemplatePreview { subject: string; body: string; html: string }
interface FormState { enabled: boolean; subject_template: string; body_template: string }

function toForm(template: MessageTemplate): FormState {
  return {
    enabled: template.enabled,
    subject_template: template.subject_template,
    body_template: template.body_template,
  };
}

export function MessageTemplatesSettings() {
  const client = useQueryClient();
  const query = useQuery({
    queryKey: ["message-templates"],
    queryFn: () => api<MessageTemplate[]>("/settings/messages"),
  });
  const [selectedEvent, setSelectedEvent] = useState("");
  const [form, setForm] = useState<FormState>({ enabled: true, subject_template: "", body_template: "" });
  const [preview, setPreview] = useState<MessageTemplatePreview | null>(null);

  const selected = useMemo(
    () => query.data?.find((template) => template.event_type === selectedEvent) ?? query.data?.[0],
    [query.data, selectedEvent],
  );

  useEffect(() => {
    if (!selected) return;
    setSelectedEvent(selected.event_type);
    setForm(toForm(selected));
    setPreview({ subject: selected.preview_subject, body: selected.preview_body, html: "" });
  }, [selected?.event_type, selected?.subject_template, selected?.body_template, selected?.enabled]);

  const save = useMutation({
    mutationFn: () => api<MessageTemplate>(`/settings/messages/${selectedEvent}`, json("PUT", form)),
    onSuccess: (result) => {
      const current = client.getQueryData<MessageTemplate[]>(["message-templates"]) ?? [];
      client.setQueryData(
        ["message-templates"],
        current.map((template) => template.event_type === result.event_type ? result : template),
      );
      setPreview({ subject: result.preview_subject, body: result.preview_body, html: "" });
    },
  });

  const reset = useMutation({
    mutationFn: () => api<void>(`/settings/messages/${selectedEvent}`, { method: "DELETE" }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["message-templates"] }),
  });

  const previewMutation = useMutation({
    mutationFn: () => api<MessageTemplatePreview>("/settings/messages/preview", json("POST", {
      event_type: selectedEvent,
      subject_template: form.subject_template,
      body_template: form.body_template,
    })),
    onSuccess: setPreview,
  });

  const update = (key: keyof FormState) => (event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    save.reset();
    previewMutation.reset();
    setForm((current) => ({ ...current, [key]: key === "enabled" ? (event.target as HTMLInputElement).checked : event.target.value }));
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    save.mutate();
  };

  const insertVariable = (variable: string) => {
    previewMutation.reset();
    setForm((current) => ({ ...current, body_template: `${current.body_template}{{${variable}}}` }));
  };

  return (
    <>
      <h2>Messages</h2>
      <p>Customize account-wide email messages sent through HighLevel. Changes affect new deliveries and are protected by the durable outbox retry system.</p>
      {query.isLoading ? <div className="loading">Loading…</div> : query.error ? <div className="error-banner">{query.error.message}</div> : selected ? (
        <div className="message-settings">
          <label className="field">
            <span>Message type</span>
            <select value={selected.event_type} onChange={(event) => { save.reset(); previewMutation.reset(); setSelectedEvent(event.target.value); }}>
              {(query.data ?? []).map((template) => <option key={template.event_type} value={template.event_type}>{template.label}</option>)}
            </select>
          </label>
          <div className="message-status-row">
            <label className="check-field"><input type="checkbox" checked={form.enabled} onChange={update("enabled")} /><span>Enable this message</span></label>
            <span className="muted-note">{selected.is_custom ? "Custom account template" : "Using Passport default"}</span>
          </div>
          <form onSubmit={submit}>
            <label className="field full"><span>Subject</span><input value={form.subject_template} onChange={update("subject_template")} maxLength={240} /></label>
            <label className="field full"><span>Message body</span><textarea rows={12} value={form.body_template} onChange={update("body_template")} maxLength={20000} /></label>
            <div className="merge-fields">
              <strong>Available merge fields</strong>
              <span>Click a field to append it to the message body. Unknown fields are rejected when saving.</span>
              <div>{selected.available_variables.map((variable) => <button type="button" className="merge-field" key={variable} onClick={() => insertVariable(variable)}>{`{{${variable}}}`}</button>)}</div>
            </div>
            {(save.error || reset.error || previewMutation.error) && <div className="error-banner" style={{ marginTop: 12 }}>{(save.error || reset.error || previewMutation.error)?.message}</div>}
            <div className="dialog-actions">
              {save.isSuccess && <span className="muted-note" style={{ alignSelf: "center" }}>Saved</span>}
              <button type="button" className="button secondary" disabled={reset.isPending || !selected.is_custom} onClick={() => reset.mutate()}>{reset.isPending ? "Restoring…" : "Restore default"}</button>
              <button type="button" className="button secondary" disabled={previewMutation.isPending} onClick={() => previewMutation.mutate()}>{previewMutation.isPending ? "Previewing…" : "Preview"}</button>
              <button className="button" disabled={save.isPending}>{save.isPending ? "Saving…" : "Save message"}</button>
            </div>
          </form>
          {preview && <section className="message-preview-card"><div className="section-heading"><div><h3>Preview</h3><p>Sample values are used here. Real customer and booking values are inserted when the message is sent.</p></div></div><strong>{preview.subject}</strong><pre>{preview.body}</pre></section>}
        </div>
      ) : <div className="empty-state">No message templates are available.</div>}
    </>
  );
}
