-- Migración para el Asistente JUSTO: Nuevas tablas de eventos, chat y reportes
-- Ejecutar en Supabase (PostgreSQL)

-- 1. Tabla de Eventos de Precios (Calculados en el Backend)
CREATE TABLE IF NOT EXISTS eventos_precio (
    id_evento serial PRIMARY KEY,
    id_producto integer REFERENCES productos_fuente(id_producto_fuente) ON DELETE CASCADE NOT NULL,
    retailer text NOT NULL, -- retailer identificador (ej: 'coto', 'carrefour')
    tipo_evento text NOT NULL, -- 'aumento', 'baja', 'promocion', 'desaparicion', 'reaparicion'
    precio_anterior numeric(12, 2),
    precio_actual numeric(12, 2),
    variacion_absoluta numeric(12, 2),
    variacion_pct numeric(8, 4),
    fecha_deteccion timestamp with time zone DEFAULT now() NOT NULL,
    id_captura_anterior integer REFERENCES capturas_precio(id_captura) ON DELETE SET NULL,
    id_captura_actual integer REFERENCES capturas_precio(id_captura) ON DELETE CASCADE,
    validado boolean DEFAULT false NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ep_producto ON eventos_precio(id_producto);
CREATE INDEX IF NOT EXISTS idx_ep_fecha ON eventos_precio(fecha_deteccion);
CREATE INDEX IF NOT EXISTS idx_ep_retailer ON eventos_precio(retailer);

-- 2. Tabla de Conversaciones del Chat IA
CREATE TABLE IF NOT EXISTS conversaciones_ia (
    id_conversacion serial PRIMARY KEY,
    id_cliente integer REFERENCES clientes(id_cliente) ON DELETE CASCADE NOT NULL,
    id_usuario integer REFERENCES usuarios_cliente(id_usuario) ON DELETE CASCADE NOT NULL,
    fecha_inicio timestamp with time zone DEFAULT now() NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_cia_cliente ON conversaciones_ia(id_cliente);
CREATE INDEX IF NOT EXISTS idx_cia_usuario ON conversaciones_ia(id_usuario);

-- 3. Tabla de Mensajes del Chat IA
CREATE TABLE IF NOT EXISTS mensajes_ia (
    id_mensaje serial PRIMARY KEY,
    id_conversacion integer REFERENCES conversaciones_ia(id_conversacion) ON DELETE CASCADE NOT NULL,
    rol text NOT NULL, -- 'user', 'assistant'
    contenido text NOT NULL,
    fecha_hora timestamp with time zone DEFAULT now() NOT NULL,
    tools_utilizadas jsonb
);

CREATE INDEX IF NOT EXISTS idx_mia_conversacion ON mensajes_ia(id_conversacion);
CREATE INDEX IF NOT EXISTS idx_mia_fecha ON mensajes_ia(fecha_hora);

-- 4. Tabla de Reportes Excel Generados
CREATE TABLE IF NOT EXISTS reportes_generados (
    id_reporte serial PRIMARY KEY,
    id_cliente integer REFERENCES clientes(id_cliente) ON DELETE CASCADE NOT NULL,
    tipo_reporte text NOT NULL, -- 'cambios_dia', 'comparativo_competidor', 'semanal_ejecutivo'
    periodo_desde date,
    periodo_hasta date,
    archivo_url text NOT NULL,
    fecha_generacion timestamp with time zone DEFAULT now() NOT NULL,
    generado_por_usuario integer REFERENCES usuarios_cliente(id_usuario) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_rg_cliente ON reportes_generados(id_cliente);
CREATE INDEX IF NOT EXISTS idx_rg_fecha ON reportes_generados(fecha_generacion);
