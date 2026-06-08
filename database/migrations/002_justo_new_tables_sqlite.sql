-- Migración para el Asistente JUSTO: Nuevas tablas de eventos, chat y reportes (SQLite)
-- Ejecutar localmente en SQLite

-- 1. Tabla de Eventos de Precios (Calculados en el Backend)
CREATE TABLE IF NOT EXISTS eventos_precio (
    id_evento INTEGER PRIMARY KEY AUTOINCREMENT,
    id_producto INTEGER NOT NULL REFERENCES productos_fuente(id_producto_fuente) ON DELETE CASCADE,
    retailer TEXT NOT NULL,
    tipo_evento TEXT NOT NULL, -- 'aumento', 'baja', 'promocion', 'desaparicion', 'reaparicion'
    precio_anterior REAL,
    precio_actual REAL,
    variacion_absoluta REAL,
    variacion_pct REAL,
    fecha_deteccion TEXT DEFAULT (datetime('now')) NOT NULL,
    id_captura_anterior INTEGER REFERENCES capturas_precio(id_captura) ON DELETE SET NULL,
    id_captura_actual INTEGER REFERENCES capturas_precio(id_captura) ON DELETE CASCADE,
    validado INTEGER DEFAULT 0 NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ep_producto ON eventos_precio(id_producto);
CREATE INDEX IF NOT EXISTS idx_ep_fecha ON eventos_precio(fecha_deteccion);
CREATE INDEX IF NOT EXISTS idx_ep_retailer ON eventos_precio(retailer);

-- 2. Tabla de Conversaciones del Chat IA
CREATE TABLE IF NOT EXISTS conversaciones_ia (
    id_conversacion INTEGER PRIMARY KEY AUTOINCREMENT,
    id_cliente INTEGER NOT NULL REFERENCES clientes(id_cliente) ON DELETE CASCADE,
    id_usuario INTEGER NOT NULL REFERENCES usuarios_cliente(id_usuario) ON DELETE CASCADE,
    fecha_inicio TEXT DEFAULT (datetime('now')) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_cia_cliente ON conversaciones_ia(id_cliente);
CREATE INDEX IF NOT EXISTS idx_cia_usuario ON conversaciones_ia(id_usuario);

-- 3. Tabla de Mensajes del Chat IA
CREATE TABLE IF NOT EXISTS mensajes_ia (
    id_mensaje INTEGER PRIMARY KEY AUTOINCREMENT,
    id_conversacion INTEGER NOT NULL REFERENCES conversaciones_ia(id_conversacion) ON DELETE CASCADE,
    rol TEXT NOT NULL, -- 'user', 'assistant'
    contenido TEXT NOT NULL,
    fecha_hora TEXT DEFAULT (datetime('now')) NOT NULL,
    tools_utilizadas TEXT -- JSON text
);

CREATE INDEX IF NOT EXISTS idx_mia_conversacion ON mensajes_ia(id_conversacion);
CREATE INDEX IF NOT EXISTS idx_mia_fecha ON mensajes_ia(fecha_hora);

-- 4. Tabla de Reportes Excel Generados
CREATE TABLE IF NOT EXISTS reportes_generados (
    id_reporte INTEGER PRIMARY KEY AUTOINCREMENT,
    id_cliente INTEGER NOT NULL REFERENCES clientes(id_cliente) ON DELETE CASCADE,
    tipo_reporte TEXT NOT NULL, -- 'cambios_dia', 'comparativo_competidor', 'semanal_ejecutivo'
    periodo_desde TEXT,
    periodo_hasta TEXT,
    archivo_url TEXT NOT NULL,
    fecha_generacion TEXT DEFAULT (datetime('now')) NOT NULL,
    generado_por_usuario INTEGER REFERENCES usuarios_cliente(id_usuario) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_rg_cliente ON reportes_generados(id_cliente);
CREATE INDEX IF NOT EXISTS idx_rg_fecha ON reportes_generados(fecha_generacion);
