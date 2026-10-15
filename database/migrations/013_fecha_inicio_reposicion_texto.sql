-- El snapshot SPM puede informar la fecha de inicio sin año (por ejemplo
-- ``13/10``). Se conserva el valor original para no inventar una fecha.

BEGIN;
ALTER TABLE public.cobertura_reposicion
    ALTER COLUMN fecha_desde TYPE text USING fecha_desde::text;
COMMIT;
