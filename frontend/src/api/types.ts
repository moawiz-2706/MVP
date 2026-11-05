export type Id = string;

export interface UserContext {
  user: {
    id: Id;
    ghl_user_id: string;
    name: string | null;
    email: string | null;
    role: string;
    is_agency_owner: boolean;
  };
  operator: {
    id: Id;
    name: string;
    slug: string;
    time_zone: string;
    ghl_location_id: string;
  };
}

export interface PwaBootstrapResponse extends UserContext {
  permissions: string[];
  features: Record<string, boolean>;
  badge_counts: { notifications: number; staff_missing_roles: number };
}

export interface PwaDashboardCounts {
  today: number;
  upcoming: number;
  pending_payment: number;
  waivers_pending: number;
  unassigned_bookings: number;
  sync_failures: number;
  staff_conflicts: number;
}

export interface PwaDashboardAlert {
  id: string;
  title: string;
  description: string;
  href: string;
  severity: "warning" | "danger";
}

export interface PwaDashboardResponse {
  date: string;
  time_zone: string;
  today: Booking[];
  upcoming: Booking[];
  counts: PwaDashboardCounts;
  attention: PwaDashboardAlert[];
}

export interface PwaSearchResult {
  type: "booking" | "customer" | "calendar" | "staff" | "payment" | "waiver" | "note";
  id: Id;
  title: string;
  subtitle: string | null;
  status: string | null;
  href: string;
}

export interface PwaSearchResponse { query: string; results: PwaSearchResult[] }

export interface Entity { id: Id; created_at: string; updated_at: string }
export interface Location extends Entity { name: string; address: string; is_active: boolean; calendars_count: number }
export interface Resource extends Entity { name: string; resource_type: string; quantity: number; capacity_limit: number | null; notes: string | null; is_active: boolean; calendars_count: number }
export interface Category extends Entity { name: string; slug: string; display_color: string | null; sort_order: number; is_active: boolean; calendars_count: number }
export interface Calendar extends Entity {
  calendar_category_id: Id | null;
  departure_location_id: Id | null;
  name: string;
  slug: string;
  headline: string | null;
  description: string | null;
  booking_instructions: string | null;
  hero_image_url: string | null;
  gallery_image_urls: string[];
  is_active: boolean;
  public_booking_enabled: boolean;
  duration_minutes: number;
  slot_interval_minutes: number;
  max_units_per_booking: number | null;
  base_price_minor: number;
  currency: string;
  availability_mode: string;
  required_staff_roles: string[];
  minimum_party_size: number | null;
  maximum_party_size: number | null;
  booking_fee_bps: number;
  tax_bps: number;
  public_booking_mode: string;
  booking_cutoff_minutes: number | null;
  call_to_book_phone: string | null;
  lowest_rate_minor?: number | null;
  active_rate_count?: number;
  single_rate_name?: string | null;
}
export interface CalendarHour extends Entity { calendar_id: Id; day_of_week: number; start_time: string; end_time: string }
export interface CalendarDateHour extends Entity { calendar_id: Id; start_date: string; end_date: string; start_time: string; end_time: string }
export interface CalendarBlock extends Entity { calendar_id: Id; start_at: string; end_at: string; start_date: string; end_date: string; reason: string | null }
export interface CalendarResource { resource_id: Id; name: string; total_quantity: number; default_quantity_per_unit: number }
export interface CustomerType extends Entity { name: string; plural_name: string; note: string | null; seat_count: number; external_provider: string | null; external_id: string | null; is_active: boolean }
export interface CalendarRateResource { resource_id: Id; name: string; quantity_per_unit: number; total_quantity: number }
export interface CalendarRate extends Entity { calendar_id: Id; customer_type_id: Id; customer_type_name: string; customer_type_plural_name: string; customer_type_note: string | null; seat_count: number; price_minor: number; booking_fee_bps: number; tax_bps: number; is_tax_inclusive: boolean; is_fee_inclusive: boolean; external_provider: string | null; external_id: string | null; is_active: boolean; resources: CalendarRateResource[]; duration_minutes?: number | null; min_units_per_booking?: number | null; max_units_per_booking?: number | null; max_units_per_departure?: number | null }
export interface PushedSlot extends Entity { calendar_id: Id; start_at: string; end_at: string }

export interface StaffHour { day_of_week: number; start_time: string; end_time: string }
export interface Staff extends Entity { name: string; email: string | null; phone: string | null; is_active: boolean; hours: StaffHour[]; upcoming_assignments: number; ghl_user_id: string | null; ghl_user_sync_status: string; ghl_user_last_error: string | null; ghl_permissions_verified_at: string | null; custom_role: string | null; availability_time_zone: string | null; availability_sync_status: string; availability_last_error: string | null; availability_last_synced_at: string | null }
export interface StaffBookingLinkResponse { staff_id: Id; token: string; path: string; expires_at: string }
export interface StaffCandidate { staff_id: Id; name: string; custom_role: string | null; available: boolean; reason: string | null }
export interface StaffAssignment { id: Id; staff_id: Id; staff_name: string; calendar_id: Id; start_at: string; end_at: string; role: string | null }
export interface GHLStaffDetails { staff_id: Id; ghl_user_id: string; profile: Record<string, unknown>; time_zone: string | null; hours: StaffHour[]; window_start?: string | null; window_end?: string | null; window_count?: number; availability_sync_status: string; availability_last_synced_at: string | null }

export interface Booking {
  id: Id;
  booking_order_id: Id;
  public_reference: string;
  calendar_id: Id;
  calendar_name: string;
  category_id: Id | null;
  category_name: string | null;
  category_color: string | null;
  customer_name: string;
  customer_email: string;
  start_at: string;
  end_at: string;
  units: number;
  status: string;
}

export interface SlotStaff { id: Id; staff_id: Id; staff_name: string; role: string | null }
export interface SlotCalendar { calendar_id: Id; calendar_name: string; category_color: string | null; end_at: string; pushed: boolean; bookings: Booking[]; staff: SlotStaff[]; capacity: number | null; booked_units: number }
/** Everything starting at one instant on the dashboard, grouped by calendar. */
export interface DashboardSlot { start_at: string; calendars: SlotCalendar[] }

export interface BookingDetail extends Booking {
  booking_source?: string | null;
  partner_id?: Id | null;
  partner_split?: PartnerSplit | null;
  created_by_name?: string | null;
  customer_phone: string | null;
  marketing_opt_in: boolean;
  location_name: string | null;
  location_address: string | null;
  payment_status: string;
  payment_method: string;
  invoice_status: string | null;
  invoice_url: string | null;
  subtotal_minor: number;
  platform_fee_and_taxes_minor: number;
  customer_total_minor: number;
  rate_id: Id | null;
  customer_type_name: string | null;
  seat_count: number;
  booking_fee_minor: number;
  tax_minor: number;
  line_total_minor: number;
  booking_policy_version: number | null;
  ghl_contact_sync_status: string;
  ghl_confirmation_email_status: string;
  ghl_appointment_sync_status: string;
  ghl_appointment_event_id: string | null;
  ghl_appointment_last_error: string | null;
  resources: { resource_id: Id; name: string; quantity: number }[];
  created_at: string;
  waiver: WaiverSummary;
  notes: BookingNote[];
  participants: BookingParticipant[];
}

export interface BookingNotification {
  booking_id: Id;
  calendar_id: Id;
  calendar_name: string;
  customer_name: string;
  start_at: string;
  end_at: string;
  units: number;
  status: string;
  created_at: string;
  assignment_status: "pending" | "completed";
  captain_name: string | null;
  reason: string | null;
}

export interface BookingNotificationsResponse {
  items: BookingNotification[];
  pending_count: number;
}

export type NotificationType = "booking_staff" | "calendar_availability" | "calendar_resources" | "ghl_sync_failed" | "ghl_workflow_trigger_failed";
export interface WorkflowTriggerDelivery {
  ghl_workflow_id: string;
  status: string;
  attempt_count: number;
  last_http_status: number | null;
  last_error: string | null;
  last_attempt_at: string | null;
  delivered_at: string | null;
}
export interface WorkflowTriggerEvent {
  id: Id;
  event_type: string;
  event_id: string;
  status: string;
  occurred_at: string;
  delivered_at: string | null;
  last_error: string | null;
  deliveries: WorkflowTriggerDelivery[];
}
export interface WorkflowTriggerOrderStatus {
  booking_order_id: Id;
  enabled: boolean;
  events: WorkflowTriggerEvent[];
}
export interface NotificationItem {
  id: string;
  type: NotificationType;
  title: string;
  description: string;
  action_label: string;
  calendar_id: Id;
  calendar_name: string;
  booking_id: Id | null;
  customer_name: string | null;
  start_at: string | null;
  end_at: string | null;
  required_roles: string[];
  missing_roles: string[];
  order_id: Id | null;
  sync_run_id: Id | null;
  sync_attempts: number | null;
  error_code: string | null;
}
export interface NotificationsResponse {
  items: NotificationItem[];
  pending_count: number;
  generated_at: string;
}

export interface PublicCalendar {
  id: Id;
  name: string;
  slug: string;
  headline: string | null;
  description: string | null;
  booking_instructions: string | null;
  hero_image_url: string | null;
  gallery_image_urls: string[];
  duration_minutes: number;
  base_price_minor: number;
  from_price_minor?: number | null;
  currency: string;
  category_id: Id | null;
  category_name: string | null;
  category_slug: string | null;
  category_color: string | null;
  location: { name: string; address: string } | null;
  public_booking_mode: string;
  booking_cutoff_minutes: number | null;
  call_to_book_phone: string | null;
  booking_policy: PublicBookingPolicy | null;
}

export interface PublicCatalog { name: string; slug: string; time_zone: string; calendars: PublicCalendar[] }
export interface PublicCategoryPage { operator_name: string; operator_slug: string; time_zone: string; category_name: string; category_slug: string; calendars: PublicCalendar[] }
export interface PublicRateResource { resource_id: Id; name: string; quantity_per_unit: number; total_quantity: number }
export interface PublicRate { id: Id; customer_type_name: string; customer_type_plural_name: string; note: string | null; seat_count: number; price_minor: number; booking_fee_bps: number; tax_bps: number; resources: PublicRateResource[]; duration_minutes?: number | null; min_units_per_booking?: number | null; max_units_per_booking?: number | null }
export interface PublicBookingPolicy { cancellation_cutoff_minutes: number; cancellation_fee_bps: number; weather_refund_mode: string; reschedule_cutoff_minutes: number; reschedule_fee_minor: number; no_show_mode: string; requires_waiver: boolean }
export interface PublicCustomField { id: Id; key: string; label: string; field_type: string; required: boolean; options: unknown[] | null }
export interface AvailabilitySlot { start_at: string; end_at: string; max_bookable_units: number; available: boolean; status?: string; rates?: SlotRate[] }
export interface SlotRate { rate_id: Id; customer_type_name: string; seat_count: number; available_quantity: number; available_seats: number; duration_minutes?: number | null; min_units_per_booking?: number | null; max_units_per_booking?: number | null }
export interface AvailabilityMonth { month: string; time_zone: string; days: { date: string; status: "available" | "sold_out" | "none" }[] }
export interface AvailabilityResponse { date: string; time_zone: string; calendar: unknown; slots: AvailabilitySlot[] }

export interface WaiverGuest { guest_number: number; status: "signed" | "pending"; url: string; signed_at: string | null; signed_by: string | null }
export interface WaiverSummary { status: "signed" | "pending" | "not_set_up" | "not_applicable"; signed_at: string | null; url: string | null; signed_count?: number | null; total?: number | null; guests?: WaiverGuest[] }
export interface BookingNote { id: Id; author_user_id: Id | null; author_name: string | null; body: string; created_at: string }
export interface BookingParticipant { id: Id; sequence: number; first_name: string; last_name: string; email: string | null; phone: string | null; date_of_birth: string | null; is_minor: boolean; guardian_name: string | null; emergency_contact: Record<string, unknown> | null; operational_notes: string | null; status: string; source: string }
export interface ReportSummary { start_date: string; end_date: string; total_bookings: number; confirmed_bookings: number; pending_payment_bookings: number; cancelled_bookings: number; completed_bookings: number; units_booked: number; gross_sales_minor: number; booking_fees_minor: number; taxes_minor: number; upcoming_bookings: number; failed_sync_jobs: number }

export interface WaiverPerson { first_name: string; last_name: string; date_of_birth: string; email?: string; phone?: string }
export interface WaiverSigner extends WaiverPerson { email: string; phone: string }
export interface WaiverAddress { street: string; city: string; state: string; postal_code: string; country: string }
export interface SignedWaiverDetails { signer: WaiverSigner; address: WaiverAddress; participants: (WaiverPerson & { minor: boolean })[]; opt_in: boolean; opt_in_label: string | null }
export interface PublicWaiver {
  status: "pending" | "signed" | "unavailable";
  unavailable_reason: string | null;
  operator_name: string;
  title: string;
  website: string | null;
  activity_name: string;
  activity_start_at: string;
  activity_end_at: string;
  time_zone: string;
  participants_total: number;
  guest_number?: number | null;
  guest_total?: number | null;
  waiver_text: string | null;
  opt_in_label: string | null;
  prefill: { first_name: string; last_name: string; email: string; phone: string | null } | null;
  signed_at: string | null;
  details: SignedWaiverDetails | null;
  signature_png: string | null;
}
export interface WaiverSettingsData { waiver_title: string | null; waiver_website: string | null; waiver_text: string | null; waiver_opt_in_label: string | null }

export interface MessageTemplate {
  event_type: string;
  label: string;
  enabled: boolean;
  subject_template: string;
  body_template: string;
  is_custom: boolean;
  available_variables: string[];
  preview_subject: string;
  preview_body: string;
}

export interface PwaDepartureResource {
  resource_id: string;
  name: string;
  total: number;
  confirmed: number;
  held: number;
  remaining: number;
}

export interface PwaDepartureBooking {
  id: string;
  public_reference: string;
  lead_name: string;
  status: string;
  payment_status: string | null;
  payment_method: string | null;
  units: number;
}

export interface PwaDepartureStaff {
  assignment_id: string;
  staff_id: string;
  staff_name: string;
  role: string | null;
}

export interface PwaDeparture {
  calendar_id: string;
  calendar_name: string;
  category_color: string | null;
  start_at: string;
  end_at: string;
  source: "scheduled" | "pushed" | "unscheduled";
  blocked: boolean;
  resources: PwaDepartureResource[];
  bookings: PwaDepartureBooking[];
  staff: PwaDepartureStaff[];
  booked_units: number;
}

export interface PwaDeparturesResponse {
  date: string;
  time_zone: string;
  departures: PwaDeparture[];
}

export interface PwaManifestParticipant {
  id: string;
  sequence: number;
  name: string;
  is_minor: boolean;
  guardian_name: string | null;
  phone: string | null;
  email: string | null;
  checked_in_at: string | null;
}

export interface PwaManifestBooking {
  id: string;
  public_reference: string;
  lead_name: string;
  lead_phone: string | null;
  lead_email: string;
  status: string;
  payment_status: string | null;
  payment_method: string | null;
  units: number;
  waiver_status: "signed" | "pending" | "none";
  participants: PwaManifestParticipant[];
}

export interface PwaManifestResponse {
  calendar_id: string;
  calendar_name: string;
  start_at: string;
  end_at: string;
  time_zone: string;
  expected_units: number;
  named_participants: number;
  checked_in: number;
  staff: PwaDepartureStaff[];
  bookings: PwaManifestBooking[];
}

export type WeatherRefundMode = "full_refund" | "credit" | "manual_review" | "no_refund";

export interface PwaClosurePreview {
  manifest: PwaManifestResponse;
  default_refund_mode: WeatherRefundMode;
  already_closed: boolean;
}

export interface PwaCloseDepartureResponse {
  closure_id: string;
  cancelled_bookings: number;
  refund_mode: string;
  failed: { booking_id: string; error: string }[];
}

export interface CreatorReportRow {
  booking_source: string | null;
  staff_id: string | null;
  user_id: string | null;
  creator_name: string;
  orders: number;
  confirmed_orders: number;
  cancelled_orders: number;
  gross_minor: number;
  refunded_minor: number;
  currency: string;
}

export interface CreatorReport {
  start_date: string;
  end_date: string;
  rows: CreatorReportRow[];
}

export interface Partner {
  id: Id;
  name: string;
  code: string;
  hotel_commission_bps: number;
  pga_commission_bps: number;
  is_active: boolean;
  booking_link: string;
  created_at: string;
}
export interface PartnerSplit {
  source_partner: string;
  gross_minor: number;
  hotel_commission_minor: number;
  pga_commission_minor: number;
  net_to_operator_minor: number;
  gratuity_minor: number;
}
export interface PartnerCommissionRow extends Omit<PartnerSplit, "gratuity_minor"> {
  partner_id: Id | null;
  bookings: number;
  guests: number;
  currency: string;
}
export interface PartnerCommissionReport {
  start_date: string;
  end_date: string;
  rows: PartnerCommissionRow[];
}
