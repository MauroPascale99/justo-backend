-- ============================================================================
-- Analytics / Share de surtido - migracion ADITIVA v1
-- ----------------------------------------------------------------------------
-- Solo CREATE TABLE/INDEX nuevos con prefijo an_. NO toca tablas existentes
-- (sin ALTER/DROP sobre lo que ya hay). Reversible: ver bloque DOWN al final.
--
-- Capas:
--   GLOBAL (un snapshot semanal sirve a todos los clientes):
--     an_snapshot, an_product_observation
--   POR CLIENTE (taxonomia sembrada desde sus productos, editable):
--     an_canonical_category, an_category_map,
--     an_category_snapshot, an_category_share, an_brand_share
-- ============================================================================

-- Taxonomia canonica POR CLIENTE -------------------------------------------------
create table if not exists an_canonical_category (
  id            bigint generated always as identity primary key,
  id_cliente    integer not null,
  categoria     text    not null,
  subcategoria  text,                       -- NULL = nodo de categoria (nivel 1)
  slug          text,
  activa        boolean not null default true,
  creado_en     timestamptz not null default now(),
  unique (id_cliente, categoria, subcategoria)
);

-- Mapa retailer (categoria cruda) -> canonica. SIEMPRE guarda el original -------
create table if not exists an_category_map (
  id                    bigint generated always as identity primary key,
  id_cliente            integer not null,
  retailer              text    not null,
  categoria_original    text    not null,   -- path crudo tal cual lo da el retail
  canonical_category_id bigint  not null references an_canonical_category(id) on delete cascade,
  activo                boolean not null default true,
  creado_en             timestamptz not null default now(),
  unique (id_cliente, retailer, categoria_original)
);
create index if not exists ix_an_catmap_lookup
  on an_category_map (retailer, categoria_original) where activo;

-- Cabecera del snapshot semanal (GLOBAL, inmutable) -----------------------------
create table if not exists an_snapshot (
  id            bigint generated always as identity primary key,
  snapshot_date date    not null,
  iso_year      integer not null,
  iso_week      integer not null,
  estado        text    not null default 'en_proceso',  -- en_proceso|completo|error
  origen        text    not null default 'catalogo_semanal',
  started_at    timestamptz not null default now(),
  finished_at   timestamptz,
  total_obs     integer,
  unique (iso_year, iso_week, origen)
);

-- Observaciones crudas por SKU dentro del snapshot (GLOBAL) ---------------------
-- Dedup: 1 fila por (snapshot, retailer, categoria_original, dedup_key).
-- dedup_key = coalesce(ean, 'url:'||url) -> mismo SKU repetido en una categoria
-- cuenta 1, aun sin EAN. Mismo SKU en dos categorias = cuenta en cada una.
create table if not exists an_product_observation (
  id                  bigint generated always as identity primary key,
  snapshot_id         bigint  not null references an_snapshot(id) on delete cascade,
  retailer            text    not null,
  categoria_original  text    not null,
  ean                 text,
  marca               text,
  seller              text,
  in_stock            boolean,
  price               numeric,
  dedup_key           text    not null,
  creado_en           timestamptz not null default now(),
  unique (snapshot_id, retailer, categoria_original, dedup_key)
);
create index if not exists ix_an_obs_snap on an_product_observation (snapshot_id);
create index if not exists ix_an_obs_cat  on an_product_observation (snapshot_id, retailer, categoria_original);
create index if not exists ix_an_obs_ean  on an_product_observation (snapshot_id, ean);

-- Rollup por (cliente, snapshot, retailer, canonica) ----------------------------
create table if not exists an_category_snapshot (
  id                    bigint generated always as identity primary key,
  snapshot_id           bigint  not null references an_snapshot(id) on delete cascade,
  id_cliente            integer not null,
  snapshot_date         date    not null,
  retailer              text    not null,
  canonical_category_id bigint  not null references an_canonical_category(id) on delete cascade,
  total_skus            integer not null default 0,
  total_in_stock        integer,
  avg_price             numeric,
  creado_en             timestamptz not null default now(),
  unique (snapshot_id, id_cliente, retailer, canonical_category_id)
);

-- Lo que consume Analytics: share de surtido (POR CLIENTE, materializado) -------
create table if not exists an_category_share (
  id                    bigint generated always as identity primary key,
  snapshot_id           bigint  not null references an_snapshot(id) on delete cascade,
  id_cliente            integer not null,
  snapshot_date         date    not null,
  retailer              text    not null,    -- retailer o 'CONSOLIDADO'
  canonical_category_id bigint  not null references an_canonical_category(id) on delete cascade,
  nivel                 text    not null,    -- 'categoria' | 'subcategoria'
  own_skus              integer not null default 0,
  total_skus            integer not null default 0,
  share_surtido         numeric,             -- own/total
  category_size         integer not null default 0,
  creado_en             timestamptz not null default now(),
  unique (snapshot_id, id_cliente, retailer, canonical_category_id, nivel)
);
create index if not exists ix_an_share_cliente on an_category_share (id_cliente, snapshot_date);

-- Ranking competitivo por marca (POR CLIENTE, materializado) --------------------
create table if not exists an_brand_share (
  id                    bigint generated always as identity primary key,
  snapshot_id           bigint  not null references an_snapshot(id) on delete cascade,
  id_cliente            integer not null,
  snapshot_date         date    not null,
  retailer              text    not null,    -- retailer o 'CONSOLIDADO'
  canonical_category_id bigint  not null references an_canonical_category(id) on delete cascade,
  marca                 text    not null,
  skus                  integer not null default 0,
  share                 numeric,
  is_own                boolean not null default false,
  creado_en             timestamptz not null default now(),
  unique (snapshot_id, id_cliente, retailer, canonical_category_id, marca)
);
create index if not exists ix_an_brandshare_cliente on an_brand_share (id_cliente, snapshot_date);

-- ============================================================================
-- DOWN (reversible) - ejecutar solo para revertir por completo el modulo:
-- drop table if exists
--   an_brand_share, an_category_share, an_category_snapshot,
--   an_product_observation, an_snapshot, an_category_map, an_canonical_category
-- cascade;
-- ============================================================================
