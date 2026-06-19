-- Inteligencia comercial: descubrimiento de SKUs (altas nuevas + candidatos)
-- =========================================================================
-- Registro persistente de SKUs ya vistos. Es INMUNE a la purga de historico
-- (capturas_precio se poda, pero este registro no), por eso permite detectar
-- altas reales de la competencia con deteccion diaria "first-seen".
--
-- Aditivo y reversible: solo crea una tabla nueva, no toca nada existente.

create table if not exists intel_sku_conocido (
    id_producto_fuente bigint primary key,
    retailer           text,
    ean                text,
    primera_vez        date not null default current_date,
    creado_en          timestamptz not null default now()
);

create index if not exists ix_sku_conocido_primera on intel_sku_conocido (primera_vez);

-- rollback:
-- drop table if exists intel_sku_conocido;
