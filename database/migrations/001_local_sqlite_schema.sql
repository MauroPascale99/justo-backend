PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS fuentes (
    id_fuente INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    retailer TEXT NOT NULL UNIQUE,
    tipo_fuente TEXT NOT NULL,
    url_base TEXT,
    frecuencia_horas INTEGER DEFAULT 24,
    estado TEXT NOT NULL DEFAULT 'activa',
    ultima_captura TEXT,
    total_capturas INTEGER DEFAULT 0,
    total_errores INTEGER DEFAULT 0,
    creado_en TEXT DEFAULT (datetime('now')),
    actualizado_en TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS productos_fuente (
    id_producto_fuente INTEGER PRIMARY KEY AUTOINCREMENT,
    id_fuente INTEGER NOT NULL REFERENCES fuentes(id_fuente),
    retailer TEXT NOT NULL,
    nombre_original TEXT NOT NULL,
    url_producto TEXT,
    url_imagen TEXT,
    categoria_original TEXT,
    subcategoria_original TEXT,
    ean_detectado TEXT,
    marca_original TEXT,
    tipo_marca TEXT,
    fecha_alta TEXT DEFAULT (datetime('now')),
    ultima_vez_visto TEXT DEFAULT (datetime('now')),
    estado TEXT NOT NULL DEFAULT 'activo',
    UNIQUE(id_fuente, url_producto)
);

CREATE INDEX IF NOT EXISTS idx_pf_fuente ON productos_fuente(id_fuente);
CREATE INDEX IF NOT EXISTS idx_pf_ean ON productos_fuente(ean_detectado);
CREATE INDEX IF NOT EXISTS idx_pf_retailer ON productos_fuente(retailer);
CREATE INDEX IF NOT EXISTS idx_pf_marca ON productos_fuente(marca_original);

CREATE TABLE IF NOT EXISTS capturas_precio (
    id_captura INTEGER PRIMARY KEY AUTOINCREMENT,
    id_producto_fuente INTEGER NOT NULL REFERENCES productos_fuente(id_producto_fuente),
    fecha_captura TEXT NOT NULL,
    hora_captura TEXT NOT NULL,
    precio_actual REAL,
    precio_regular REAL,
    precio_oferta REAL,
    precio_por_unidad REAL,
    unidad_precio TEXT,
    tipo_promocion TEXT,
    texto_promocion TEXT,
    disponibilidad INTEGER DEFAULT 1,
    hash_captura TEXT NOT NULL,
    score_confianza_dato REAL DEFAULT 0.0,
    estado_captura TEXT DEFAULT 'ok',
    error_detalle TEXT,
    es_cambio_precio INTEGER DEFAULT 0,
    creado_en TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_cp_producto ON capturas_precio(id_producto_fuente);
CREATE INDEX IF NOT EXISTS idx_cp_fecha ON capturas_precio(fecha_captura);
CREATE INDEX IF NOT EXISTS idx_cp_hash ON capturas_precio(hash_captura);
CREATE INDEX IF NOT EXISTS idx_cp_tipo_promo ON capturas_precio(tipo_promocion);

CREATE TABLE IF NOT EXISTS auditoria_capturas (
    id_auditoria INTEGER PRIMARY KEY AUTOINCREMENT,
    id_fuente INTEGER REFERENCES fuentes(id_fuente),
    retailer TEXT,
    fecha_inicio TEXT,
    fecha_fin TEXT,
    duracion_segundos REAL,
    total_productos INTEGER DEFAULT 0,
    total_exitosos INTEGER DEFAULT 0,
    total_errores INTEGER DEFAULT 0,
    total_cambios_precio INTEGER DEFAULT 0,
    estado_corrida TEXT,
    detalle TEXT,
    creado_en TEXT DEFAULT (datetime('now'))
);

CREATE VIEW IF NOT EXISTS v_precios_actuales AS
SELECT
    pf.retailer,
    pf.nombre_original,
    pf.url_producto,
    pf.url_imagen,
    pf.ean_detectado,
    pf.marca_original,
    pf.tipo_marca,
    pf.categoria_original,
    pf.subcategoria_original,
    cp.fecha_captura,
    cp.hora_captura,
    cp.precio_actual,
    cp.precio_regular,
    cp.precio_oferta,
    cp.precio_por_unidad,
    cp.unidad_precio,
    cp.tipo_promocion,
    cp.texto_promocion,
    cp.disponibilidad,
    cp.score_confianza_dato,
    cp.estado_captura
FROM capturas_precio cp
JOIN productos_fuente pf ON pf.id_producto_fuente = cp.id_producto_fuente
WHERE cp.id_captura = (
    SELECT MAX(cp2.id_captura)
    FROM capturas_precio cp2
    WHERE cp2.id_producto_fuente = cp.id_producto_fuente
);

INSERT OR IGNORE INTO fuentes (nombre, retailer, tipo_fuente, url_base, frecuencia_horas, estado)
VALUES
    ('Coto', 'coto', 'atg_json', 'https://www.cotodigital.com.ar', 24, 'activa'),
    ('Día', 'dia', 'vtex', 'https://diaonline.supermercadosdia.com.ar', 24, 'activa'),
    ('Chango Más', 'changomas', 'vtex', 'https://www.changomas.com.ar', 24, 'activa');
