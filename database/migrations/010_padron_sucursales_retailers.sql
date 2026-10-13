-- Padrón nacional de sucursales. La fuente oficial y la fecha de verificación
-- permiten actualizar el mapa sin depender de resultados de búsqueda parciales.

BEGIN;

CREATE TABLE IF NOT EXISTS public.sucursales_retailer (
    id_sucursal bigserial PRIMARY KEY,
    retailer text NOT NULL,
    codigo_externo text,
    nombre text NOT NULL,
    direccion text NOT NULL,
    localidad text,
    provincia text,
    codigo_postal text,
    latitud numeric(10,7),
    longitud numeric(10,7),
    fuente_url text NOT NULL,
    verificado_en timestamp with time zone NOT NULL DEFAULT now(),
    activa boolean NOT NULL DEFAULT true,
    creado_en timestamp with time zone NOT NULL DEFAULT now(),
    actualizado_en timestamp with time zone NOT NULL DEFAULT now(),
    CONSTRAINT sucursales_retailer_retailer_direccion_unique UNIQUE (retailer, direccion, localidad)
);

CREATE INDEX IF NOT EXISTS idx_sucursales_retailer_mapa
    ON public.sucursales_retailer (retailer, activa, provincia);

ALTER TABLE public.sucursales_retailer ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS sucursales_retailer_lectura_autenticada ON public.sucursales_retailer;
CREATE POLICY sucursales_retailer_lectura_autenticada ON public.sucursales_retailer
    FOR SELECT TO authenticated USING (true);

COMMIT;
