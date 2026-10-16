-- Vincula la evidencia de Góndolas perfectas con el punto operativo del mapa.

BEGIN;

ALTER TABLE public.gondolas_perfectas
    ADD COLUMN IF NOT EXISTS clave_sucursal text REFERENCES public.cobertura_sucursales(clave) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_gondolas_perfectas_sucursal
    ON public.gondolas_perfectas (id_cliente, clave_sucursal, creado_en DESC);

COMMIT;
