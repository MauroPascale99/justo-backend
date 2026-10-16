-- Conserva el período original del reporte para mostrar la semana o mes
-- correspondiente junto a las métricas de cada sucursal.
BEGIN;

ALTER TABLE public.cobertura_metricas_sucursal
    ADD COLUMN IF NOT EXISTS fecha_corte date,
    ADD COLUMN IF NOT EXISTS periodo_venta text;

CREATE INDEX IF NOT EXISTS idx_cobertura_metricas_fecha_corte
    ON public.cobertura_metricas_sucursal (fecha_corte);

COMMIT;
