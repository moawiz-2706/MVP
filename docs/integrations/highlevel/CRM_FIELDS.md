# HighLevel fields Passport fills

Passport finds fields **by their key**, which HighLevel builds from the field
name (lowercase, spaces become `_`). Create each field with the name below,
check the **Key** column on Settings → Custom Fields, and Passport starts
filling it on the next booking change. No ids to copy. A field you don't
create is simply skipped. Use **Single line** for every field unless noted;
Passport sends text.

## Contact: standard field

| HighLevel field | Filled with |
|---|---|
| **Date of birth** (built-in) | The lead booker's date of birth from the waiver (the participant with the booking email, else the first adult). Set when the waiver is signed. |

Name, email and phone are the contact's own standard fields, already kept in sync.

## Contact: custom fields (object: Contact, folder "Passport")

Shows the customer's most recent Passport booking.

| Field name | Key | Filled with |
|---|---|---|
| Passport Booking Reference | `passport_booking_reference` | e.g. RM-94QRPMG43MRYM8V |
| Passport Booking ID | `passport_booking_id` | Passport order id |
| Passport Booking Status | `passport_booking_status` | pending_payment, confirmed, cancelled, … |
| Passport Payment Status | `passport_payment_status` | requires_payment, succeeded, refunded, … |
| Passport Service Name | `passport_service_name` | Activity, e.g. "The Oasis" BYOB Sunset Cruise - Public |
| Passport Tour Start | `passport_tour_start` | Wednesday, December 9, 2026 at 5:15 PM |
| Passport Start At | `passport_start_at` | Start, ISO UTC |
| Passport End At | `passport_end_at` | End, ISO UTC |
| Passport Quantity | `passport_quantity` | Guests |
| Passport Total | `passport_total` | Total charged, e.g. 133.34 |
| Passport Currency | `passport_currency` | USD |
| Passport Source Partner | `passport_source_partner` | Direct, Sunseeker, … |
| Passport Waiver URL | `passport_waiver_url` | Waiver link (opens the signed waiver once signed) |
| Passport Waiver Status | `passport_waiver_status` | pending, signed, not_applicable |
| Passport Waiver Signed At | `passport_waiver_signed_at` | When it was signed, ISO UTC |
| Passport Waiver Expires At | `passport_waiver_expires_at` | When the link stops working, ISO UTC |
| Passport Emergency Contact | `passport_emergency_contact` | From the lead booker's waiver |
| Passport Marketing Opt In | `passport_marketing_opt_in` | true / false |
| Passport Guest List | `passport_guest_list` | Everyone in the party, one per line: name (adult/minor), email, phone. Large text field |

## Passport Bookings object: fields (object: Passport Booking)

One record per booking, linked to the contact ("Customer Booking"). The first
five already exist.

| Field name | Key | Filled with |
|---|---|---|
| Booking Reference *(primary, exists)* | `booking_reference` | RM-… |
| Passport Booking ID *(exists)* | `passport_booking_id` | Passport order id |
| Payment Status *(exists)* | `payment_status` | requires_payment, succeeded, refunded, … |
| Invoice Status *(exists)* | `invoice_status` | Stripe invoice status, if invoiced |
| Waiver Status *(exists)* | `waiver_status` | pending, signed, not_applicable |
| Booking Status | `booking_status` | pending_payment, confirmed, cancelled, … |
| Payment Method | `payment_method` | card, invoice, none |
| Customer Name | `customer_name` | Alex Smith |
| Customer Email | `customer_email` | alex@example.com |
| Customer Phone | `customer_phone` | +1… |
| Activity | `activity` | Activity name(s) |
| Tour Start | `tour_start` | Wednesday, December 9, 2026 at 5:15 PM |
| Guests | `guests` | 2 |
| Total Amount | `total_amount` | 133.34 |
| Source Partner | `source_partner` | Direct, Sunseeker, … |
| Assigned Staff | `assigned_staff` | Captain names |
| Waiver Link | `waiver_link` | Link to the waiver (shows the signed waiver once signed) |
| Waiver Signed At | `waiver_signed_at` | ISO UTC |
| Emergency Contact | `emergency_contact` | From the lead booker's waiver |
| Guest List | `guest_list` | Everyone in the party, one per line: name (adult/minor), email, phone. Large text field |

## When values update

- **Record and contact:** on booking created, payment confirmed, rescheduled, party size or payment change, and cancelled.
- **Waiver signed:** the record's waiver fields, plus the contact's date of birth, emergency contact and waiver fields, within about a minute. Phone and date of birth are only filled in when the contact has none.
- **Other guests:** every adult on a waiver (or added by staff in the booking drawer) who gives an email gets their own contact, tagged `passport-guest`, and is linked to the booking's Passport Booking record. The record and the lead contact get the guest list.

Scopes the app needs: `locations/customFields.readonly` (contact field lookup), `objects/schema.readonly` (object field list), `objects/record.readonly`, `objects/record.write`, `associations.readonly`, `associations/relation.write`, plus `contacts.write`. Passport requests them on install and staff PWA sign-in.
