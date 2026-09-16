import { AlertTriangle, CheckCircle2 } from "lucide-react";
import { useSearchParams } from "react-router-dom";

export function IntegrationResultPage() {
  const [searchParams] = useSearchParams();
  const hasError = searchParams.has("error") || searchParams.get("installed") !== "1";

  return (
    <div className="center-state">
      <div className="state-card">
        <div className={`success-icon${hasError ? " result-error-icon" : ""}`}>
          {hasError ? <AlertTriangle aria-hidden="true" /> : <CheckCircle2 aria-hidden="true" />}
        </div>
        <h1>{hasError ? "Installation could not be completed" : "Installation complete"}</h1>
        <p>
          {hasError
            ? "HighLevel could not finish connecting this subaccount to Passport. Return to HighLevel and try installing the app again."
            : "Your HighLevel subaccount is now connected to Passport. You can close this tab and open Passport from inside HighLevel."}
        </p>
        <button className="button secondary" onClick={() => window.close()}>
          Close this tab
        </button>
      </div>
    </div>
  );
}
