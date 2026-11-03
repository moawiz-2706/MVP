import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { api } from "../api/client";
import type { WorkflowTriggerOrderStatus } from "../api/types";

const eventLabel: Record<string, string> = {
  booking_created: "Booking created",
  booking_confirmed: "Booking confirmed",
  booking_rescheduled: "Booking rescheduled",
  payment_updated: "Payment updated",
  payment_confirmed: "Payment confirmed",
  booking_updated: "Booking updated",
  booking_cancelled: "Booking cancelled",
};

const statusLabel: Record<string, string> = {
  pending: "Waiting to send",
  delivered: "Delivered",
  partially_delivered: "Partly delivered",
  failed: "Failed",
  no_subscriber: "No workflow uses the trigger",
};

/** HighLevel Marketplace Custom Trigger delivery for one order.
 *  Separate from the contact/appointment sync shown above it. */
export function WorkflowTriggerStatus({ orderId }: { orderId: string }) {
  const client = useQueryClient();
  const status = useQuery({
    queryKey: ["workflow-trigger", orderId],
    queryFn: () => api<WorkflowTriggerOrderStatus>(`/orders/${orderId}/workflow-trigger`),
  });
  const retry = useMutation({
    mutationFn: () => api<WorkflowTriggerOrderStatus>(`/orders/${orderId}/workflow-trigger/retry`, { method: "POST" }),
    onSuccess: async (data) => {
      client.setQueryData(["workflow-trigger", orderId], data);
      await client.invalidateQueries({ queryKey: ["notifications"] });
    },
  });
  if (!status.data?.enabled) return null;
  const events = status.data.events;
  const retryable = events.some((event) => event.status === "failed" || event.status === "partially_delivered" || event.status === "no_subscriber" || (event.status === "pending" && event.last_error));
  return <div className="detail-section">
    <h3>HighLevel workflow trigger</h3>
    {events.length === 0 ? <p className="muted-note">No trigger events for this booking.</p> : <dl className="detail-list">
      {events.map((event) => <div key={event.id} style={{ display: "contents" }}>
        <dt>{eventLabel[event.event_type] || event.event_type}</dt>
        <dd>
          {statusLabel[event.status] || event.status}
          {event.status === "pending" && event.last_error && " (retrying)"}
          {event.deliveries.length > 0 && <><br /><span style={{ color: "#697386", fontWeight: 400 }}>{event.deliveries.filter((delivery) => delivery.status === "delivered").length} of {event.deliveries.length} workflow(s)</span></>}
          {event.last_error && event.status !== "delivered" && <><br /><span style={{ color: "#9b2822", fontWeight: 400, overflowWrap: "anywhere" }}>{event.last_error}</span></>}
        </dd>
      </div>)}
    </dl>}
    {retry.error && <div className="error-banner">{retry.error.message}</div>}
    {retry.isSuccess && <div className="success-banner">Workflow trigger retry queued.</div>}
    {retryable && <button className="button secondary small" disabled={retry.isPending} onClick={() => retry.mutate()}><RefreshCw size={14} />{retry.isPending ? "Retrying…" : "Retry workflow trigger"}</button>}
  </div>;
}
