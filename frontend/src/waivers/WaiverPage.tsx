import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Printer } from "lucide-react";
import { useState, type ChangeEvent, type FormEvent, type InputHTMLAttributes } from "react";
import { useParams } from "react-router-dom";
import { api, json } from "../api/client";
import type { PublicWaiver, WaiverAddress, WaiverPerson, WaiverSigner } from "../api/types";
import { SignaturePad } from "../components/SignaturePad";
import { formatLongDate, formatTime, isoDayInZone, zoneLabel } from "../lib/datetime";
import { PublicFrame } from "../public-booking/OperatorBookingPage";

const ADULT_AGE = 18;

/** Whole years between a YYYY-MM-DD birth date and a YYYY-MM-DD day. */
function ageOn(dateOfBirth: string, day: string): number {
  const [by = 0, bm = 0, bd = 0] = dateOfBirth.split("-").map(Number);
  const [y = 0, m = 0, d = 0] = day.split("-").map(Number);
  return y - by - (m < bm || (m === bm && d < bd) ? 1 : 0);
}

function formatBirthDate(value: string): string {
  const [y = 0, m = 1, d = 1] = value.split("-").map(Number);
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeZone: "UTC" }).format(new Date(Date.UTC(y, m - 1, d)));
}

const websiteHref = (value: string) => (/^https?:\/\//i.test(value) ? value : `https://${value}`);

/** Paragraphs are separated by a blank line; a paragraph wrapped in ## ... ## is shown bold. */
function WaiverText({ text }: { text: string }) {
  const blocks = text.split(/\n\s*\n/).map((block) => block.trim()).filter(Boolean);
  return (
    <div className="waiver-text">
      {blocks.map((block, index) => {
        const strong = block.length > 4 && block.startsWith("##") && block.endsWith("##");
        return <p key={index} className={strong ? "waiver-strong" : undefined}>{strong ? block.slice(2, -2).trim() : block}</p>;
      })}
    </div>
  );
}

function Field({ label, full, ...input }: { label: string; full?: boolean } & InputHTMLAttributes<HTMLInputElement>) {
  return <label className={`field${full ? " full" : ""}`}><span>{label}</span><input required {...input} /></label>;
}

function WaiverHeader({ waiver }: { waiver: PublicWaiver }) {
  const tz = waiver.time_zone;
  return (
    <>
      <h1 className="waiver-title">{waiver.title}</h1>
      <div className="waiver-meta">
        <div>
          <h3>Company</h3>
          <p>{waiver.operator_name}{waiver.website && <><br /><a href={websiteHref(waiver.website)} target="_blank" rel="noreferrer">{waiver.website}</a></>}</p>
        </div>
        <div>
          <h3>Activity</h3>
          <p>{waiver.activity_name}<br />Date of activity: {formatLongDate(waiver.activity_start_at, tz)} · {formatTime(waiver.activity_start_at, tz)} ({zoneLabel(tz)})</p>
        </div>
      </div>
    </>
  );
}

function SignedView({ waiver }: { waiver: PublicWaiver }) {
  const tz = waiver.time_zone;
  const details = waiver.details;
  if (!details || !waiver.signed_at) {
    return <div className="waiver-signed-banner"><CheckCircle2 size={18} /><span>Signed {waiver.signed_at ? `${formatLongDate(waiver.signed_at, tz)} at ${formatTime(waiver.signed_at, tz)}` : "successfully"}. This waiver is locked. The signed legal record is retained securely by the operator.</span></div>;
  }
  const signedAt = `${formatLongDate(waiver.signed_at, tz)} at ${formatTime(waiver.signed_at, tz)}`;
  const minors = details.participants.filter((person) => person.minor);
  const adults = details.participants.filter((person) => !person.minor);
  const person = (p: WaiverPerson, index: number) => (
    <dl className="detail-list waiver-person" key={index}>
      <dt>First name</dt><dd>{p.first_name}</dd>
      <dt>Last name</dt><dd>{p.last_name}</dd>
      <dt>Date of birth</dt><dd>{formatBirthDate(p.date_of_birth)}</dd>
    </dl>
  );
  return (
    <>
      <div className="waiver-signed-banner no-print">
        <CheckCircle2 size={18} />
        <span>Signed {signedAt}. This waiver is locked and cannot be changed.</span>
        <button type="button" className="button secondary small" onClick={() => window.print()}><Printer size={14} />Print or save as PDF</button>
      </div>
      {waiver.waiver_text && <WaiverText text={waiver.waiver_text} />}
      {minors.length > 0 && <section className="waiver-section"><h2>Minors</h2>{minors.map(person)}</section>}
      {adults.length > 0 && <section className="waiver-section"><h2>Other participants</h2>{adults.map(person)}</section>}
      <section className="waiver-section">
        <h2>Contact details</h2>
        <dl className="detail-list">
          <dt>First name</dt><dd>{details.signer.first_name}</dd>
          <dt>Last name</dt><dd>{details.signer.last_name}</dd>
          <dt>Email address</dt><dd>{details.signer.email}</dd>
          <dt>Date of birth</dt><dd>{formatBirthDate(details.signer.date_of_birth)}</dd>
          <dt>Phone number</dt><dd>{details.signer.phone}</dd>
        </dl>
      </section>
      <section className="waiver-section">
        <h2>Home address</h2>
        <dl className="detail-list">
          <dt>Street</dt><dd>{details.address.street}</dd>
          <dt>City</dt><dd>{details.address.city}</dd>
          <dt>State or province</dt><dd>{details.address.state}</dd>
          <dt>Postal code</dt><dd>{details.address.postal_code}</dd>
          <dt>Country</dt><dd>{details.address.country}</dd>
        </dl>
      </section>
      {details.opt_in_label && <p className="waiver-optin"><input type="checkbox" checked={details.opt_in} readOnly disabled /> {details.opt_in_label}</p>}
      <section className="waiver-section">
        <h2>Signature</h2>
        {waiver.signature_png && <img className="waiver-signature" src={waiver.signature_png} alt={`Signature of ${details.signer.first_name} ${details.signer.last_name}`} />}
        <p className="muted-note">Date of signature: {signedAt}</p>
      </section>
    </>
  );
}

function SignForm({ waiver, token }: { waiver: PublicWaiver; token: string }) {
  const client = useQueryClient();
  const tz = waiver.time_zone;
  const today = isoDayInZone(new Date(), tz);
  const activityDay = isoDayInZone(new Date(waiver.activity_start_at), tz);
  const [signer, setSigner] = useState<WaiverSigner>({
    first_name: waiver.prefill?.first_name ?? "",
    last_name: waiver.prefill?.last_name ?? "",
    email: waiver.prefill?.email ?? "",
    phone: waiver.prefill?.phone ?? "",
    date_of_birth: "",
  });
  const [address, setAddress] = useState<WaiverAddress>({ street: "", city: "", state: "", postal_code: "", country: "" });
  const [others, setOthers] = useState<WaiverPerson[]>(() =>
    Array.from({ length: Math.max(0, waiver.participants_total - 1) }, () => ({ first_name: "", last_name: "", date_of_birth: "" })),
  );
  const [optIn, setOptIn] = useState(false);
  const [agreed, setAgreed] = useState(false);
  const [signature, setSignature] = useState<string | null>(null);

  const sign = useMutation({
    mutationFn: () => api<PublicWaiver>(`/public/waivers/${token}/sign`, json("POST", { signer, address, participants: others, opt_in: optIn, agreed, signature_png: signature })),
    onSuccess: (result) => { client.setQueryData(["waiver", token], result); window.scrollTo({ top: 0, behavior: "smooth" }); },
  });

  const updateSigner = (key: keyof WaiverSigner) => (event: ChangeEvent<HTMLInputElement>) => setSigner({ ...signer, [key]: event.target.value });
  const updateAddress = (key: keyof WaiverAddress) => (event: ChangeEvent<HTMLInputElement>) => setAddress({ ...address, [key]: event.target.value });
  const updateOther = (index: number, key: keyof WaiverPerson) => (event: ChangeEvent<HTMLInputElement>) =>
    setOthers(others.map((person, i) => (i === index ? { ...person, [key]: event.target.value } : person)));
  const signerTooYoung = !!signer.date_of_birth && ageOn(signer.date_of_birth, today) < ADULT_AGE;
  const submit = (event: FormEvent) => { event.preventDefault(); if (signature && agreed && !signerTooYoung) sign.mutate(); };

  return (
    <form onSubmit={submit}>
      {waiver.waiver_text && <WaiverText text={waiver.waiver_text} />}

      <section className="waiver-section">
        <h2>Your details</h2>
        <p className="muted-note">The person signing must be 18 or older and signs on behalf of everyone listed, including any minors in their care.</p>
        <div className="form-grid">
          <Field label="First name" value={signer.first_name} onChange={updateSigner("first_name")} maxLength={120} />
          <Field label="Last name" value={signer.last_name} onChange={updateSigner("last_name")} maxLength={120} />
          <Field label="Email address" type="email" value={signer.email} onChange={updateSigner("email")} />
          <Field label="Phone number" type="tel" value={signer.phone} onChange={updateSigner("phone")} maxLength={40} />
          <Field label="Date of birth" type="date" max={today} value={signer.date_of_birth} onChange={updateSigner("date_of_birth")} />
        </div>
        {signerTooYoung && <div className="error-banner" style={{ marginTop: 10 }}>The person signing must be 18 or older.</div>}
      </section>

      <section className="waiver-section">
        <h2>Home address</h2>
        <div className="form-grid">
          <Field label="Street" full value={address.street} onChange={updateAddress("street")} maxLength={200} />
          <Field label="City" value={address.city} onChange={updateAddress("city")} maxLength={120} />
          <Field label="State or province" value={address.state} onChange={updateAddress("state")} maxLength={120} />
          <Field label="Postal code" value={address.postal_code} onChange={updateAddress("postal_code")} maxLength={30} />
          <Field label="Country" value={address.country} onChange={updateAddress("country")} maxLength={80} />
        </div>
      </section>

      {others.length > 0 && (
        <section className="waiver-section">
          <h2>Everyone else taking part</h2>
          <p className="muted-note">This booking is for {waiver.participants_total} people, so please add the other {others.length}.</p>
          {others.map((person, index) => (
            <div className="participant-block" key={index}>
              <h3>Participant {index + 2}{person.date_of_birth && ageOn(person.date_of_birth, activityDay) < ADULT_AGE && <span className="badge warning">Minor</span>}</h3>
              <div className="form-grid">
                <Field label="First name" value={person.first_name} onChange={updateOther(index, "first_name")} maxLength={120} />
                <Field label="Last name" value={person.last_name} onChange={updateOther(index, "last_name")} maxLength={120} />
                <Field label="Date of birth" type="date" max={today} value={person.date_of_birth} onChange={updateOther(index, "date_of_birth")} />
              </div>
            </div>
          ))}
        </section>
      )}

      {waiver.opt_in_label && <label className="check-field waiver-optin"><input type="checkbox" checked={optIn} onChange={(e) => setOptIn(e.target.checked)} />{waiver.opt_in_label}</label>}

      <section className="waiver-section">
        <h2>Signature</h2>
        <SignaturePad onChange={setSignature} />
      </section>

      <label className="check-field waiver-agree"><input type="checkbox" required checked={agreed} onChange={(e) => setAgreed(e.target.checked)} />I have read this waiver, understand it, and agree to it on behalf of everyone listed.</label>
      {sign.error && <div className="error-banner" style={{ marginTop: 12 }}>{sign.error.message}</div>}
      <button className="button waiver-submit" disabled={sign.isPending || !signature || !agreed || signerTooYoung}>
        {sign.isPending ? "Signing..." : signature ? "Sign waiver" : "Add your signature to continue"}
      </button>
    </form>
  );
}

export function WaiverPage() {
  const { token = "" } = useParams();
  const query = useQuery({ queryKey: ["waiver", token], queryFn: () => api<PublicWaiver>(`/public/waivers/${token}`), retry: false });
  if (query.isLoading) return <div className="center-state"><div className="spinner" /></div>;
  if (query.error || !query.data) {
    return <div className="center-state"><div className="state-card"><h1>Waiver not found</h1><p>This link may be incorrect. Please use the link from your booking email.</p></div></div>;
  }
  const waiver = query.data;
  return (
    <PublicFrame name={waiver.operator_name}>
      <article className="public-card waiver-doc">
        <WaiverHeader waiver={waiver} />
        {waiver.status === "signed" ? <SignedView waiver={waiver} />
          : waiver.status === "unavailable" ? <div className="warning-box"><p>{waiver.unavailable_reason}</p></div>
          : <>
              <h3 className="waiver-subhead">Instructions</h3>
              <p className="muted-note">Everyone taking part must be listed on this waiver. Please read it, add everyone's details, and sign at the bottom.</p>
              <SignForm waiver={waiver} token={token} />
            </>}
      </article>
    </PublicFrame>
  );
}
