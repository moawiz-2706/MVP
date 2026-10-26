import { Elements, PaymentElement, useElements, useStripe } from "@stripe/react-stripe-js";
import { loadStripe } from "@stripe/stripe-js";
import { useState, type FormEvent } from "react";

const stripePromise = loadStripe(import.meta.env.VITE_STRIPE_PUBLISHABLE_KEY || "pk_test_missing");

function AdjustmentForm({ onComplete }: { onComplete: () => void }) {
  const stripe = useStripe();
  const elements = useElements();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!stripe || !elements) return;
    setBusy(true);
    setError(null);
    const result = await stripe.confirmPayment({
      elements,
      confirmParams: { return_url: window.location.href },
      redirect: "if_required",
    });
    if (result.error) setError(result.error.message || "The additional payment could not be completed.");
    else onComplete();
    setBusy(false);
  };

  return (
    <form onSubmit={submit} className="adjustment-payment-form">
      <p className="muted-note">The booking price increased. Complete the additional payment to apply the new quantity or time.</p>
      <PaymentElement options={{ layout: "tabs" }} />
      {error && <div className="error-banner">{error}</div>}
      <button className="button" style={{ width: "100%", marginTop: 16 }} disabled={!stripe || busy}>
        {busy ? "Processing…" : "Pay additional amount"}
      </button>
    </form>
  );
}

export function AdjustmentPaymentPanel({ clientSecret, onComplete }: { clientSecret: string; onComplete: () => void }) {
  return (
    <Elements stripe={stripePromise} options={{ clientSecret, appearance: { theme: "stripe", variables: { colorPrimary: "#166b5c", borderRadius: "7px", fontFamily: "Inter, system-ui, sans-serif" } } }}>
      <AdjustmentForm onComplete={onComplete} />
    </Elements>
  );
}
