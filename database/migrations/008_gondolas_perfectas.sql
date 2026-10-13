-- Evidencia de ejecucion en punto de venta: foto, categoria, sucursal y GPS.
-- Ejecutar en Supabase SQL Editor antes de publicar el modulo.

BEGIN;

CREATE TABLE IF NOT EXISTS public.gondolas_perfectas (
    id_gondola bigserial PRIMARY KEY,
    id_cliente integer NOT NULL REFERENCES public.clientes(id_cliente) ON DELETE CASCADE,
    categoria text NOT NULL CHECK (length(trim(categoria)) BETWEEN 1 AND 120),
    retailer text,
    sucursal text NOT NULL CHECK (length(trim(sucursal)) BETWEEN 1 AND 180),
    latitud numeric(10, 7),
    longitud numeric(10, 7),
    precision_metros numeric(10, 2),
    foto_path text NOT NULL,
    observaciones text,
    creado_por uuid NOT NULL REFERENCES auth.users(id),
    creado_en timestamp with time zone NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_gondolas_perfectas_cliente_fecha
    ON public.gondolas_perfectas (id_cliente, creado_en DESC);

ALTER TABLE public.gondolas_perfectas ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS gondolas_perfectas_solo_su_cliente ON public.gondolas_perfectas;
CREATE POLICY gondolas_perfectas_solo_su_cliente ON public.gondolas_perfectas
    FOR ALL
    USING (id_cliente = get_id_cliente())
    WITH CHECK (id_cliente = get_id_cliente() AND creado_por = auth.uid());

-- Bucket privado: las fotos se exponen solo por URL firmada desde la API.
INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES (
    'gondolas-perfectas',
    'gondolas-perfectas',
    false,
    8388608,
    ARRAY['image/jpeg', 'image/png', 'image/webp']
)
ON CONFLICT (id) DO UPDATE
SET public = false,
    file_size_limit = EXCLUDED.file_size_limit,
    allowed_mime_types = EXCLUDED.allowed_mime_types;

DROP POLICY IF EXISTS gondolas_storage_select_su_cliente ON storage.objects;
CREATE POLICY gondolas_storage_select_su_cliente ON storage.objects
    FOR SELECT TO authenticated
    USING (
        bucket_id = 'gondolas-perfectas'
        AND (storage.foldername(name))[1] = get_id_cliente()::text
    );

DROP POLICY IF EXISTS gondolas_storage_insert_su_cliente ON storage.objects;
CREATE POLICY gondolas_storage_insert_su_cliente ON storage.objects
    FOR INSERT TO authenticated
    WITH CHECK (
        bucket_id = 'gondolas-perfectas'
        AND (storage.foldername(name))[1] = get_id_cliente()::text
    );

COMMIT;
