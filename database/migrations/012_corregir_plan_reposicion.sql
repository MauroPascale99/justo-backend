-- En los reportes SPM ``dias`` contiene el calendario (por ejemplo, Martes y
-- Jueves), no una cantidad. ``vis`` es la frecuencia semanal y ``mes`` el
-- total planificado del mes.

BEGIN;

ALTER TABLE public.cobertura_reposicion
    ALTER COLUMN dias_planificados TYPE text USING dias_planificados::text;

ALTER TABLE public.cobertura_reposicion
    ADD COLUMN IF NOT EXISTS visitas_semana integer;

COMMIT;
