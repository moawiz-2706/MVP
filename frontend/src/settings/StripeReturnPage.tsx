import { CheckCircle2, RefreshCw } from "lucide-react";

export function StripeReturnPage({refresh=false}:{refresh?:boolean}) {return <div className="center-state"><div className="state-card"><div className="success-icon">{refresh?<RefreshCw/>:<CheckCircle2/>}</div><h1>{refresh?"Continue Stripe setup":"Stripe setup submitted"}</h1><p>{refresh?"Return to Passport and choose Continue setup to generate a fresh secure onboarding link.":"You can close this tab and return to GoHighLevel. Refresh payment status there to see the latest account state."}</p><button className="button secondary" onClick={()=>window.close()}>Close this tab</button></div></div>}

