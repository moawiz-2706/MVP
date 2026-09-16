-- Public booking pages require a per-category slug so a Category can expose its
-- own booking URL: /book/{operator_slug}/category/{category_slug}.

ALTER TABLE calendar_categories ADD COLUMN slug text;

-- Backfill any existing rows from a slugified name; the id suffix guarantees the
-- partial-unique index below is satisfied even for duplicate names.
UPDATE calendar_categories
SET slug = btrim(regexp_replace(lower(name), '[^a-z0-9]+', '-', 'g'), '-')
           || '-' || substr(id::text, 1, 8)
WHERE slug IS NULL;

ALTER TABLE calendar_categories ALTER COLUMN slug SET NOT NULL;

-- Active categories are unique by slug within an operator. A soft-deleted
-- category releases its slug for reuse, matching the active-name uniqueness rule.
CREATE UNIQUE INDEX uq_calendar_categories_active_slug
  ON calendar_categories (operator_id, slug) WHERE deleted_at IS NULL;
