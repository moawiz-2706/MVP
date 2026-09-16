-- Staff get a HighLevel Contact (tagged passport-staff) so assignment emails and
-- booking-day reminders can be sent to them through the Conversations API.
ALTER TABLE staff ADD COLUMN ghl_contact_id text;
