import { Elements, PaymentElement, useElements, useStripe } from "@stripe/react-stripe-js";
import { loadStripe } from "@stripe/stripe-js";
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { withEmbed } from "./embed";

const stripePromise = loadStripe(import.meta.env.VITE_STRIPE_PUBLISHABLE_KEY || "pk_test_missing");

function PaymentForm({ publicReference, accessToken, embed }: { publicReference: string; accessToken?: string | null; embed: boolean }) {
  const stripe = useStripe();
  const elements = useElements();
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const suffix = accessToken ? `?access_token=${encodeURIComponent(accessToken)}` : "";
  const confirmationPath = withEmbed(`/booking/${publicReference}/confirmation${suffix}`, embed);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!stripe || !elements) return;
    setBusy(true); setError(null);
    // redirect: "if_required" keeps card payments inside the (possibly embedded) iframe.
    const result = await stripe.confirmPayment({ elements, confirmParams: { return_url: `${window.location.origin}${confirmationPath}` }, redirect: "if_required" });
    if (result.error) setError(result.error.message || "Payment could not be completed.");
    else navigate(confirmationPath);
    setBusy(false);
  };
  return <form onSubmit={submit}><PaymentElement options={{ layout: "tabs" }} />{error && <div className="error-banner" style={{marginTop: 12}}>{error}</div>}<button className="button" style={{width:"100%", marginTop:16}} disabled={!stripe || busy}>{busy ? "Processing…" : "Pay securely"}</button></form>;
}

export function PaymentPanel({ clientSecret, publicReference, accessToken, embed = false }: { clientSecret: string; publicReference: string; accessToken?: string | null; embed?: boolean }) {
  return <Elements stripe={stripePromise} options={{ clientSecret, appearance: { theme: "stripe", variables: { colorPrimary: "#166b5c", borderRadius: "7px", fontFamily: "Inter, system-ui, sans-serif" } } }}><PaymentForm publicReference={publicReference} accessToken={accessToken} embed={embed} /></Elements>;
}
