-- Precio de referencia manual por producto dentro de cada mapa guardado.
-- Permite ubicar en el gráfico SKUs sin captura y reemplazar temporalmente el
-- promedio scrapeado por un valor definido por el usuario.

BEGIN;

ALTER TABLE public.mapa_categoria_items
    ADD COLUMN IF NOT EXISTS precio_mapa numeric(12, 2);

ALTER TABLE public.mapa_categoria_items
    DROP CONSTRAINT IF EXISTS mapa_categoria_items_precio_mapa_positivo;

ALTER TABLE public.mapa_categoria_items
    ADD CONSTRAINT mapa_categoria_items_precio_mapa_positivo
    CHECK (precio_mapa IS NULL OR precio_mapa > 0);

COMMIT;
