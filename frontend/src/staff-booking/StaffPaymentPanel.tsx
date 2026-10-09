import { Elements, PaymentElement, useElements, useStripe } from "@stripe/react-stripe-js";
import { loadStripe } from "@stripe/stripe-js";
import { useState, type FormEvent } from "react";

const stripePromise = loadStripe(import.meta.env.VITE_STRIPE_PUBLISHABLE_KEY || "pk_test_missing");

function PaymentForm({ returnUrl, onSuccess }: { returnUrl: string; onSuccess: () => void }) {
  const stripe = useStripe();
  const elements = useElements();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!stripe || !elements) return;
    setBusy(true);
    setError(null);
    const result = await stripe.confirmPayment({
      elements,
      confirmParams: { return_url: returnUrl },
      redirect: "if_required",
    });
    if (result.error) {
      setError(result.error.message || "Payment could not be completed.");
      setBusy(false);
      return;
    }
    onSuccess();
    setBusy(false);
  };

  return (
    <form onSubmit={submit}>
      <PaymentElement options={{ layout: "tabs" }} />
      {error && <div className="error-banner" style={{ marginTop: 12 }}>{error}</div>}
      <button className="button" style={{ width: "100%", marginTop: 16 }} disabled={!stripe || busy}>
        {busy ? "Processing payment…" : "Pay securely by card"}
      </button>
    </form>
  );
}

export function StaffPaymentPanel({ clientSecret, returnUrl, onSuccess }: { clientSecret: string; returnUrl: string; onSuccess: () => void }) {
  return (
    <Elements stripe={stripePromise} options={{ clientSecret, appearance: { theme: "stripe", variables: { colorPrimary: "#166b5c", borderRadius: "7px", fontFamily: "Inter, system-ui, sans-serif" } } }}>
      <PaymentForm returnUrl={returnUrl} onSuccess={onSuccess} />
    </Elements>
  );
}
