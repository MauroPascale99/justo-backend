-- ============================================================================
-- Listas de precios del cliente (ADITIVO)
-- ----------------------------------------------------------------------------
-- Precio de lista (SIN IVA) al que el cliente le vende a cada retailer, por EAN.
-- Permite calcular el markup del retailer (gondola/1.21 / lista - 1) y simular
-- escenarios de precio. Carga via Excel/CSV: RETAILER, EAN, PRECIO_LISTA.
--
-- DOWN: drop table if exists listas_precio_cliente;
-- ============================================================================
create table if not exists listas_precio_cliente (
  id              bigint generated always as identity primary key,
  id_cliente      integer not null,
  retailer        text    not null,
  ean             text    not null,
  precio_lista    numeric not null,        -- sin IVA
  volumen_estimado numeric,                 -- unidades/mes estimadas (para simular facturacion)
  moneda          text    not null default 'ARS',
  vigente_desde   date    not null default current_date,
  activo          boolean not null default true,
  creado_en       timestamptz not null default now(),
  actualizado_en  timestamptz not null default now(),
  unique (id_cliente, retailer, ean)
);
create index if not exists ix_listas_cliente on listas_precio_cliente (id_cliente) where activo;
