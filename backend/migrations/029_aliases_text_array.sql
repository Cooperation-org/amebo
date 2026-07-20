-- 029: organizations.aliases is TEXT[] everywhere.
--
-- schema.sql declares aliases TEXT[] and the code inserts text[] (3ed3a62),
-- but databases initialized before that carry the old JSONB column — on
-- those, every org provision 500s with "column aliases is of type jsonb but
-- expression is of type text[]". Convert only when the drift exists; already-
-- correct databases (fresh installs, the cohort VM) no-op.

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'organizations'
          AND column_name = 'aliases'
          AND data_type = 'jsonb'
    ) THEN
        -- USING can't hold a subquery, so convert via a replacement column
        ALTER TABLE organizations ADD COLUMN aliases_txt TEXT[] DEFAULT '{}';
        UPDATE organizations
           SET aliases_txt = COALESCE(
                   (SELECT array_agg(x) FROM jsonb_array_elements_text(aliases) AS x),
                   '{}'
               )
         WHERE aliases IS NOT NULL;
        ALTER TABLE organizations DROP COLUMN aliases;
        ALTER TABLE organizations RENAME COLUMN aliases_txt TO aliases;
    END IF;
END
$$;
