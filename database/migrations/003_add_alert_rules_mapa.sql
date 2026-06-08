-- Agregar columnas de alertas a mapa_competitivo_cliente en Supabase (PostgreSQL)

ALTER TABLE mapa_competitivo_cliente 
ADD COLUMN IF NOT EXISTS alertar_suba_competidor boolean DEFAULT true NOT NULL,
ADD COLUMN IF NOT EXISTS alertar_baja_competidor boolean DEFAULT true NOT NULL,
ADD COLUMN IF NOT EXISTS alertar_suba_propio boolean DEFAULT true NOT NULL,
ADD COLUMN IF NOT EXISTS alertar_baja_propio boolean DEFAULT true NOT NULL,
ADD COLUMN IF NOT EXISTS alertar_promocion boolean DEFAULT true NOT NULL,
ADD COLUMN IF NOT EXISTS alertar_ausencia boolean DEFAULT true NOT NULL,
ADD COLUMN IF NOT EXISTS umbral_variacion_pct numeric(5, 2) DEFAULT 5.0 NOT NULL,
ADD COLUMN IF NOT EXISTS es_competidor_principal boolean DEFAULT false NOT NULL;
