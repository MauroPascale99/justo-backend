-- Agregar columnas de alertas a mapa_competitivo_cliente en SQLite
-- (Nota: SQLite no soporta ADD COLUMN IF NOT EXISTS de forma estándar en algunas versiones, pero se define aquí para inicialización)

ALTER TABLE mapa_competitivo_cliente ADD COLUMN alertar_suba_competidor INTEGER DEFAULT 1 NOT NULL;
ALTER TABLE mapa_competitivo_cliente ADD COLUMN alertar_baja_competidor INTEGER DEFAULT 1 NOT NULL;
ALTER TABLE mapa_competitivo_cliente ADD COLUMN alertar_suba_propio INTEGER DEFAULT 1 NOT NULL;
ALTER TABLE mapa_competitivo_cliente ADD COLUMN alertar_baja_propio INTEGER DEFAULT 1 NOT NULL;
ALTER TABLE mapa_competitivo_cliente ADD COLUMN alertar_promocion INTEGER DEFAULT 1 NOT NULL;
ALTER TABLE mapa_competitivo_cliente ADD COLUMN alertar_ausencia INTEGER DEFAULT 1 NOT NULL;
ALTER TABLE mapa_competitivo_cliente ADD COLUMN umbral_variacion_pct REAL DEFAULT 5.0 NOT NULL;
ALTER TABLE mapa_competitivo_cliente ADD COLUMN es_competidor_principal INTEGER DEFAULT 0 NOT NULL;
