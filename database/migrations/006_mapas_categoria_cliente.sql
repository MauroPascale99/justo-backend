-- Mapas de arquitectura de precios guardados por cliente.
-- Ejecutar en Supabase antes de publicar el frontend que los utiliza.

BEGIN;

CREATE TABLE IF NOT EXISTS public.mapas_categoria_cliente (
    id_mapa_categoria bigserial PRIMARY KEY,
    id_cliente integer NOT NULL REFERENCES public.clientes(id_cliente) ON DELETE CASCADE,
    nombre text NOT NULL CHECK (length(trim(nombre)) BETWEEN 1 AND 100),
    creado_en timestamp with time zone NOT NULL DEFAULT now(),
    actualizado_en timestamp with time zone NOT NULL DEFAULT now(),
    UNIQUE (id_cliente, nombre)
);

CREATE TABLE IF NOT EXISTS public.mapa_categoria_items (
    id_item bigserial PRIMARY KEY,
    id_mapa_categoria bigint NOT NULL REFERENCES public.mapas_categoria_cliente(id_mapa_categoria) ON DELETE CASCADE,
    tipo text NOT NULL CHECK (tipo IN ('propio', 'competencia')),
    id_producto_cliente text,
    ean_competidor text,
    nombre_competidor text,
    marca_competidor text,
    CONSTRAINT mapa_categoria_item_identidad CHECK (
        (tipo = 'propio' AND id_producto_cliente IS NOT NULL AND ean_competidor IS NULL)
        OR (tipo = 'competencia' AND ean_competidor IS NOT NULL AND id_producto_cliente IS NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_mapas_categoria_cliente_cliente ON public.mapas_categoria_cliente(id_cliente);
CREATE INDEX IF NOT EXISTS idx_mapa_categoria_items_mapa ON public.mapa_categoria_items(id_mapa_categoria);

ALTER TABLE public.mapas_categoria_cliente ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS mapas_categoria_cliente_solo_su_cliente ON public.mapas_categoria_cliente;
CREATE POLICY mapas_categoria_cliente_solo_su_cliente ON public.mapas_categoria_cliente
    FOR ALL USING (id_cliente = get_id_cliente()) WITH CHECK (id_cliente = get_id_cliente());

ALTER TABLE public.mapa_categoria_items ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS mapa_categoria_items_solo_su_cliente ON public.mapa_categoria_items;
CREATE POLICY mapa_categoria_items_solo_su_cliente ON public.mapa_categoria_items
    FOR ALL USING (
        EXISTS (
            SELECT 1 FROM public.mapas_categoria_cliente m
            WHERE m.id_mapa_categoria = mapa_categoria_items.id_mapa_categoria
              AND m.id_cliente = get_id_cliente()
        )
    ) WITH CHECK (
        EXISTS (
            SELECT 1 FROM public.mapas_categoria_cliente m
            WHERE m.id_mapa_categoria = mapa_categoria_items.id_mapa_categoria
              AND m.id_cliente = get_id_cliente()
        )
    );

COMMIT;
