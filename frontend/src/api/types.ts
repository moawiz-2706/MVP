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

export interface Entity { id: Id; created_at: string; updated_at: string }
export interface Location extends Entity { name: string; address: string; is_active: boolean; calendars_count: number }
export interface Resource extends Entity { name: string; quantity: number; is_active: boolean; calendars_count: number }
export interface Category extends Entity { name: string; slug: string; display_color: string | null; sort_order: number; is_active: boolean; calendars_count: number }
export interface Calendar extends Entity {
  calendar_category_id: Id | null;
  departure_location_id: Id | null;
  name: string;
  slug: string;
  description: string | null;
  is_active: boolean;
  public_booking_enabled: boolean;
  duration_minutes: number;
  slot_interval_minutes: number;
  max_units_per_booking: number | null;
  base_price_minor: number;
  currency: string;
  availability_mode: string;
}
export interface CalendarHour extends Entity { calendar_id: Id; day_of_week: number; start_time: string; end_time: string }
export interface CalendarDateHour extends Entity { calendar_id: Id; start_date: string; end_date: string; start_time: string; end_time: string }
export interface CalendarBlock extends Entity { calendar_id: Id; start_at: string; end_at: string; start_date: string; end_date: string; reason: string | null }
export interface CalendarResource { resource_id: Id; name: string; total_quantity: number; default_quantity_per_unit: number }
export interface PushedSlot extends Entity { calendar_id: Id; start_at: string; end_at: string }

export interface StaffHour { day_of_week: number; start_time: string; end_time: string }
export interface Staff extends Entity { name: string; email: string | null; phone: string | null; is_active: boolean; hours: StaffHour[]; upcoming_assignments: number; ghl_user_id: string | null; ghl_user_sync_status: string; ghl_user_last_error: string | null; ghl_permissions_verified_at: string | null; custom_role: string | null; availability_time_zone: string | null; availability_sync_status: string; availability_last_error: string | null; availability_last_synced_at: string | null }
export interface StaffCandidate { staff_id: Id; name: string; custom_role: string | null; available: boolean; reason: string | null }
export interface StaffAssignment { id: Id; staff_id: Id; staff_name: string; calendar_id: Id; start_at: string; end_at: string; role: string | null }
export interface GHLStaffDetails { staff_id: Id; ghl_user_id: string; profile: Record<string, unknown>; time_zone: string | null; hours: StaffHour[]; availability_sync_status: string; availability_last_synced_at: string | null }

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
export interface SlotCalendar { calendar_id: Id; calendar_name: string; category_color: string | null; end_at: string; pushed: boolean; bookings: Booking[]; staff: SlotStaff[] }
/** Everything starting at one instant on the dashboard, grouped by calendar. */
export interface DashboardSlot { start_at: string; calendars: SlotCalendar[] }

export interface BookingDetail extends Booking {
  customer_phone: string | null;
  location_name: string | null;
  location_address: string | null;
  payment_status: string;
  subtotal_minor: number;
  platform_fee_and_taxes_minor: number;
  customer_total_minor: number;
  ghl_contact_sync_status: string;
  ghl_confirmation_email_status: string;
  ghl_appointment_sync_status: string;
  ghl_appointment_event_id: string | null;
  ghl_appointment_last_error: string | null;
  resources: { resource_id: Id; name: string; quantity: number }[];
  created_at: string;
  waiver: WaiverSummary;
  notes: BookingNote[];
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

export interface PublicCalendar {
  id: Id;
  name: string;
  slug: string;
  description: string | null;
  duration_minutes: number;
  base_price_minor: number;
  currency: string;
  category_id: Id | null;
  category_name: string | null;
  category_slug: string | null;
  category_color: string | null;
  location: { name: string; address: string } | null;
}

export interface PublicCatalog { name: string; slug: string; time_zone: string; calendars: PublicCalendar[] }
export interface PublicCategoryPage { operator_name: string; operator_slug: string; time_zone: string; category_name: string; category_slug: string; calendars: PublicCalendar[] }
export interface AvailabilitySlot { start_at: string; end_at: string; max_bookable_units: number; available: boolean }
export interface AvailabilityResponse { date: string; time_zone: string; calendar: unknown; slots: AvailabilitySlot[] }

export interface WaiverSummary { status: "signed" | "pending" | "not_set_up" | "not_applicable"; signed_at: string | null; url: string | null }
export interface BookingNote { id: Id; author_user_id: Id | null; author_name: string | null; body: string; created_at: string }

export interface WaiverPerson { first_name: string; last_name: string; date_of_birth: string }
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
  waiver_text: string | null;
  opt_in_label: string | null;
  prefill: { first_name: string; last_name: string; email: string; phone: string | null } | null;
  signed_at: string | null;
  details: SignedWaiverDetails | null;
  signature_png: string | null;
}
export interface WaiverSettingsData { waiver_title: string | null; waiver_website: string | null; waiver_text: string | null; waiver_opt_in_label: string | null }
