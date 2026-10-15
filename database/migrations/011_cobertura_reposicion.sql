-- Datos operativos de cobertura y reposición importados desde los reportes SPM.
-- Las métricas se guardan por sucursal para que el mapa no dependa de un HTML
-- estático ni de una consulta a Power BI durante la navegación.

BEGIN;

CREATE TABLE IF NOT EXISTS public.cobertura_sucursales (
    clave text PRIMARY KEY,
    cadena text NOT NULL,
    banner text,
    codigo text,
    nombre text NOT NULL,
    direccion text NOT NULL,
    partido text,
    provincia text,
    zona text,
    latitud numeric(10,7) NOT NULL,
    longitud numeric(10,7) NOT NULL,
    precision_geografica text,
    fuente text NOT NULL DEFAULT 'REPORTES SPM',
    actualizado_en timestamp with time zone NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_cobertura_sucursales_filtros
    ON public.cobertura_sucursales (cadena, banner, zona);

CREATE TABLE IF NOT EXISTS public.cobertura_reposicion (
    clave_sucursal text PRIMARY KEY REFERENCES public.cobertura_sucursales(clave) ON DELETE CASCADE,
    tiene_reposicion boolean NOT NULL DEFAULT false,
    visitas_mes integer,
    visitas_realizadas integer,
    visitas_pendientes integer,
    dias_planificados integer,
    fecha_desde date,
    nota text,
    fuente text,
    actualizado_en timestamp with time zone NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.cobertura_metricas_sucursal (
    clave_sucursal text PRIMARY KEY REFERENCES public.cobertura_sucursales(clave) ON DELETE CASCADE,
    venta_unidades_periodos jsonb NOT NULL DEFAULT '[]'::jsonb,
    venta_pesos_periodos jsonb,
    venta_semanal_unidades numeric,
    venta_semanal_pesos numeric,
    stock_unidades numeric,
    stock_pesos numeric,
    skus jsonb NOT NULL DEFAULT '[]'::jsonb,
    actualizado_en timestamp with time zone NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_cobertura_metricas_oportunidades
    ON public.cobertura_metricas_sucursal (venta_semanal_unidades, stock_unidades);

ALTER TABLE public.cobertura_sucursales ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.cobertura_reposicion ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.cobertura_metricas_sucursal ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS cobertura_sucursales_lectura_autenticada ON public.cobertura_sucursales;
CREATE POLICY cobertura_sucursales_lectura_autenticada ON public.cobertura_sucursales
    FOR SELECT TO authenticated USING (true);
DROP POLICY IF EXISTS cobertura_reposicion_lectura_autenticada ON public.cobertura_reposicion;
CREATE POLICY cobertura_reposicion_lectura_autenticada ON public.cobertura_reposicion
    FOR SELECT TO authenticated USING (true);
DROP POLICY IF EXISTS cobertura_metricas_sucursal_lectura_autenticada ON public.cobertura_metricas_sucursal;
CREATE POLICY cobertura_metricas_sucursal_lectura_autenticada ON public.cobertura_metricas_sucursal
    FOR SELECT TO authenticated USING (true);

COMMIT;
