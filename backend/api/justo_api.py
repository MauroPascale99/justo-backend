from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import sqlite3
from typing import Optional, List
from pydantic import BaseModel

DB_PATH = "db/justo_pricing.db"


class ClienteCreate(BaseModel):
    nombre_cliente: str
    rubro: Optional[str] = None
    descripcion: Optional[str] = None


class ProductoPropioCreate(BaseModel):
    id_producto_fuente: int
    sku_cliente: Optional[str] = None


class CompetidorCreate(BaseModel):
    id_producto_competidor_fuente: int
    rol_competidor: str
    margen_esperado_pct: Optional[float] = None
    brecha_minima_pct: Optional[float] = None
    brecha_maxima_pct: Optional[float] = None
    comentario_estrategia: Optional[str] = None


class CategoriaClienteCreate(BaseModel):
    retailer: str
    categoria: str
    categoria_id: Optional[str] = None
    prioridad: Optional[str] = "media"



app = FastAPI(
    title="JUSTO Pricing API",
    description="API local para catálogo maestro, productos del cliente y mapa competitivo.",
    version="0.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def limpiar_tokens(q: str) -> List[str]:
    return [t.strip().lower() for t in q.split() if t.strip()]


@app.get("/")
def home():
    return {
        "status": "ok",
        "sistema": "JUSTO Pricing API",
        "version": "0.1.0"
    }


@app.get("/catalogo/buscar")
def buscar_catalogo(
    q: str = Query(..., description="Texto a buscar: marca, producto, EAN o categoría"),
    retailer: Optional[str] = Query(None, description="Filtrar por retailer: coto, dia, changomas"),
    categoria: Optional[str] = Query(None, description="Filtrar por categoría"),
    solo_disponibles: bool = Query(False, description="Mostrar solo productos disponibles"),
    limit: int = Query(50, ge=1, le=200)
):
    tokens = limpiar_tokens(q)

    if not tokens:
        return {
            "total": 0,
            "resultados": []
        }

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    sql = """
    SELECT
        pf.id_producto_fuente,
        pf.retailer,
        pf.categoria_original AS categoria,
        pf.subcategoria_original AS subcategoria,
        pf.nombre_original AS nombre_producto,
        pf.marca_original AS marca,
        pf.ean_detectado AS ean,
        cp.precio_actual,
        cp.precio_regular,
        cp.precio_oferta,
        cp.tipo_promocion,
        cp.disponibilidad,
        pf.url_producto,
        pf.url_imagen
    FROM productos_fuente pf
    LEFT JOIN capturas_precio cp
        ON cp.id_producto_fuente = pf.id_producto_fuente
    WHERE 1 = 1
    """

    params = []

    for token in tokens:
        sql += """
        AND (
            lower(COALESCE(pf.nombre_original, '')) LIKE ?
            OR lower(COALESCE(pf.marca_original, '')) LIKE ?
            OR lower(COALESCE(pf.ean_detectado, '')) LIKE ?
            OR lower(COALESCE(pf.categoria_original, '')) LIKE ?
            OR lower(COALESCE(pf.subcategoria_original, '')) LIKE ?
        )
        """
        like = f"%{token}%"
        params.extend([like, like, like, like, like])

    if retailer:
        sql += " AND lower(pf.retailer) = ?"
        params.append(retailer.lower())

    if categoria:
        sql += " AND lower(COALESCE(pf.categoria_original, '')) LIKE ?"
        params.append(f"%{categoria.lower()}%")

    if solo_disponibles:
        sql += " AND COALESCE(cp.disponibilidad, 0) = 1 AND cp.precio_actual IS NOT NULL"

    sql += """
    ORDER BY
        COALESCE(cp.disponibilidad, 0) DESC,
        cp.precio_actual IS NULL,
        pf.retailer,
        pf.nombre_original
    LIMIT ?
    """

    params.append(limit)

    cur.execute(sql, params)
    rows = cur.fetchall()
    conn.close()

    resultados = [dict(row) for row in rows]

    return {
        "query": q,
        "total": len(resultados),
        "resultados": resultados
    }


@app.get("/catalogo/producto/{id_producto_fuente}")
def obtener_producto(id_producto_fuente: int):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
    SELECT
        pf.id_producto_fuente,
        pf.retailer,
        pf.categoria_original AS categoria,
        pf.subcategoria_original AS subcategoria,
        pf.nombre_original AS nombre_producto,
        pf.marca_original AS marca,
        pf.ean_detectado AS ean,
        cp.precio_actual,
        cp.precio_regular,
        cp.precio_oferta,
        cp.tipo_promocion,
        cp.disponibilidad,
        pf.url_producto,
        pf.url_imagen
    FROM productos_fuente pf
    LEFT JOIN capturas_precio cp
        ON cp.id_producto_fuente = pf.id_producto_fuente
    WHERE pf.id_producto_fuente = ?
    """, (id_producto_fuente,))

    row = cur.fetchone()
    conn.close()

    if not row:
        return {
            "encontrado": False,
            "producto": None
        }

    return {
        "encontrado": True,
        "producto": dict(row)
    }


# ============================================================
# CLIENTES / PROVEEDORES
# ============================================================

@app.post("/clientes")
def crear_cliente(data: ClienteCreate):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    nombre = data.nombre_cliente.strip()

    if not nombre:
        conn.close()
        return {
            "ok": False,
            "error": "El nombre del cliente es obligatorio."
        }

    cur.execute("""
    SELECT id_cliente, nombre_cliente, rubro, descripcion, estado, fecha_alta
    FROM clientes
    WHERE lower(nombre_cliente) = lower(?)
    """, (nombre,))

    existente = cur.fetchone()

    if existente:
        conn.close()
        return {
            "ok": True,
            "mensaje": "El cliente ya existía.",
            "cliente": dict(existente)
        }

    cur.execute("""
    INSERT INTO clientes (
        nombre_cliente,
        rubro,
        descripcion,
        estado
    )
    VALUES (?, ?, ?, 'activo')
    """, (
        nombre,
        data.rubro,
        data.descripcion
    ))

    id_cliente = cur.lastrowid
    conn.commit()

    cur.execute("""
    SELECT id_cliente, nombre_cliente, rubro, descripcion, estado, fecha_alta
    FROM clientes
    WHERE id_cliente = ?
    """, (id_cliente,))

    cliente = dict(cur.fetchone())
    conn.close()

    return {
        "ok": True,
        "mensaje": "Cliente creado correctamente.",
        "cliente": cliente
    }


@app.get("/clientes")
def listar_clientes():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
    SELECT
        c.id_cliente,
        c.nombre_cliente,
        c.rubro,
        c.descripcion,
        c.estado,
        c.fecha_alta,
        COUNT(pc.id_producto_cliente) AS productos_propios
    FROM clientes c
    LEFT JOIN productos_cliente pc
        ON pc.id_cliente = c.id_cliente
       AND pc.activo = 1
    GROUP BY
        c.id_cliente,
        c.nombre_cliente,
        c.rubro,
        c.descripcion,
        c.estado,
        c.fecha_alta
    ORDER BY c.fecha_alta DESC
    """)

    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    return {
        "total": len(rows),
        "clientes": rows
    }


@app.get("/clientes/{id_cliente}")
def obtener_cliente(id_cliente: int):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
    SELECT id_cliente, nombre_cliente, rubro, descripcion, estado, fecha_alta, actualizado_en
    FROM clientes
    WHERE id_cliente = ?
    """, (id_cliente,))

    row = cur.fetchone()

    if not row:
        conn.close()
        return {
            "encontrado": False,
            "cliente": None
        }

    cliente = dict(row)

    cur.execute("""
    SELECT COUNT(*)
    FROM productos_cliente
    WHERE id_cliente = ?
      AND activo = 1
    """, (id_cliente,))

    cliente["productos_propios"] = cur.fetchone()[0]

    cur.execute("""
    SELECT COUNT(*)
    FROM mapa_competitivo_cliente
    WHERE id_cliente = ?
      AND activo = 1
    """, (id_cliente,))

    cliente["competidores_asociados"] = cur.fetchone()[0]

    conn.close()

    return {
        "encontrado": True,
        "cliente": cliente
    }


# ============================================================
# PRODUCTOS PROPIOS DEL CLIENTE
# ============================================================

@app.post("/clientes/{id_cliente}/productos-propios")
def agregar_producto_propio(id_cliente: int, data: ProductoPropioCreate):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Validar cliente
    cur.execute("""
    SELECT id_cliente, nombre_cliente
    FROM clientes
    WHERE id_cliente = ?
      AND estado = 'activo'
    """, (id_cliente,))

    cliente = cur.fetchone()

    if not cliente:
        conn.close()
        return {
            "ok": False,
            "error": "Cliente no encontrado o inactivo."
        }

    # Buscar producto fuente
    cur.execute("""
    SELECT
        pf.id_producto_fuente,
        pf.retailer,
        pf.categoria_original AS categoria,
        pf.subcategoria_original AS subcategoria,
        pf.nombre_original AS nombre_producto,
        pf.marca_original AS marca,
        pf.ean_detectado AS ean,
        cp.precio_actual,
        cp.disponibilidad,
        pf.url_producto
    FROM productos_fuente pf
    LEFT JOIN capturas_precio cp
        ON cp.id_producto_fuente = pf.id_producto_fuente
    WHERE pf.id_producto_fuente = ?
    """, (data.id_producto_fuente,))

    producto = cur.fetchone()

    if not producto:
        conn.close()
        return {
            "ok": False,
            "error": "Producto fuente no encontrado."
        }

    producto = dict(producto)

    # Evitar duplicados activos
    cur.execute("""
    SELECT id_producto_cliente
    FROM productos_cliente
    WHERE id_cliente = ?
      AND id_producto_fuente = ?
      AND activo = 1
    """, (id_cliente, data.id_producto_fuente))

    existente = cur.fetchone()

    if existente:
        conn.close()
        return {
            "ok": True,
            "mensaje": "El producto ya estaba marcado como propio.",
            "id_producto_cliente": existente["id_producto_cliente"],
            "producto": producto
        }

    cur.execute("""
    INSERT INTO productos_cliente (
        id_cliente,
        id_producto_fuente,
        sku_cliente,
        ean,
        nombre_producto,
        marca,
        categoria,
        retailer,
        rol,
        activo
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PRODUCTO_PROPIO', 1)
    """, (
        id_cliente,
        data.id_producto_fuente,
        data.sku_cliente,
        producto.get("ean"),
        producto.get("nombre_producto"),
        producto.get("marca"),
        producto.get("categoria"),
        producto.get("retailer")
    ))

    id_producto_cliente = cur.lastrowid
    conn.commit()

    conn.close()

    return {
        "ok": True,
        "mensaje": "Producto marcado como propio correctamente.",
        "id_producto_cliente": id_producto_cliente,
        "producto": producto
    }


@app.get("/clientes/{id_cliente}/productos-propios")
def listar_productos_propios(id_cliente: int):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
    SELECT
        pc.id_producto_cliente,
        pc.id_cliente,
        pc.id_producto_fuente,
        pc.sku_cliente,
        pc.ean,
        pc.nombre_producto,
        pc.marca,
        pc.categoria,
        pc.retailer,
        pc.rol,
        pc.activo,
        pc.fecha_alta,
        cp.precio_actual,
        cp.precio_regular,
        cp.precio_oferta,
        cp.tipo_promocion,
        cp.disponibilidad,
        pf.url_producto,
        pf.url_imagen
    FROM productos_cliente pc
    LEFT JOIN productos_fuente pf
        ON pf.id_producto_fuente = pc.id_producto_fuente
    LEFT JOIN capturas_precio cp
        ON cp.id_producto_fuente = pc.id_producto_fuente
    WHERE pc.id_cliente = ?
      AND pc.activo = 1
    ORDER BY pc.fecha_alta DESC
    """, (id_cliente,))

    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    return {
        "id_cliente": id_cliente,
        "total": len(rows),
        "productos_propios": rows
    }


@app.delete("/clientes/{id_cliente}/productos-propios/{id_producto_cliente}")
def eliminar_producto_propio(id_cliente: int, id_producto_cliente: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
    SELECT id_producto_cliente
    FROM productos_cliente
    WHERE id_cliente = ?
      AND id_producto_cliente = ?
      AND activo = 1
    """, (id_cliente, id_producto_cliente))

    row = cur.fetchone()

    if not row:
        conn.close()
        return {
            "ok": False,
            "error": "Producto propio no encontrado o ya estaba inactivo."
        }

    # Baja lógica, no borrado físico.
    cur.execute("""
    UPDATE productos_cliente
    SET activo = 0
    WHERE id_cliente = ?
      AND id_producto_cliente = ?
    """, (id_cliente, id_producto_cliente))

    conn.commit()
    conn.close()

    return {
        "ok": True,
        "mensaje": "Producto propio desactivado correctamente."
    }



# ============================================================
# MAPA COMPETITIVO DEL CLIENTE
# ============================================================

ROLES_COMPETIDOR_VALIDOS = {
    "COMPETIDOR_DIRECTO",
    "LIDER_CATEGORIA",
    "ALTERNATIVA_ECONOMICA",
    "MARCA_PROPIA",
    "SUSTITUTO",
}


@app.post("/clientes/{id_cliente}/productos-propios/{id_producto_cliente}/competidores")
def agregar_competidor_producto(
    id_cliente: int,
    id_producto_cliente: int,
    data: CompetidorCreate
):
    rol = data.rol_competidor.strip().upper()

    if rol not in ROLES_COMPETIDOR_VALIDOS:
        return {
            "ok": False,
            "error": "Rol competidor inválido.",
            "roles_validos": sorted(list(ROLES_COMPETIDOR_VALIDOS))
        }

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Validar cliente
    cur.execute("""
    SELECT id_cliente, nombre_cliente
    FROM clientes
    WHERE id_cliente = ?
      AND estado = 'activo'
    """, (id_cliente,))

    cliente = cur.fetchone()

    if not cliente:
        conn.close()
        return {
            "ok": False,
            "error": "Cliente no encontrado o inactivo."
        }

    # Validar producto propio
    cur.execute("""
    SELECT
        id_producto_cliente,
        id_producto_fuente,
        nombre_producto,
        marca,
        ean,
        retailer,
        categoria
    FROM productos_cliente
    WHERE id_cliente = ?
      AND id_producto_cliente = ?
      AND activo = 1
    """, (id_cliente, id_producto_cliente))

    producto_propio = cur.fetchone()

    if not producto_propio:
        conn.close()
        return {
            "ok": False,
            "error": "Producto propio no encontrado o inactivo."
        }

    # Validar competidor fuente
    cur.execute("""
    SELECT
        pf.id_producto_fuente,
        pf.retailer,
        pf.categoria_original AS categoria,
        pf.subcategoria_original AS subcategoria,
        pf.nombre_original AS nombre_producto,
        pf.marca_original AS marca,
        pf.ean_detectado AS ean,
        cp.precio_actual,
        cp.precio_regular,
        cp.precio_oferta,
        cp.tipo_promocion,
        cp.disponibilidad,
        pf.url_producto
    FROM productos_fuente pf
    LEFT JOIN capturas_precio cp
        ON cp.id_producto_fuente = pf.id_producto_fuente
    WHERE pf.id_producto_fuente = ?
    """, (data.id_producto_competidor_fuente,))

    competidor = cur.fetchone()

    if not competidor:
        conn.close()
        return {
            "ok": False,
            "error": "Producto competidor fuente no encontrado."
        }

    competidor = dict(competidor)

    # Evitar asociar el mismo producto fuente como competidor de sí mismo
    if producto_propio["id_producto_fuente"] == data.id_producto_competidor_fuente:
        conn.close()
        return {
            "ok": False,
            "error": "No se puede asociar el mismo producto propio como competidor."
        }

    # Evitar duplicados activos
    cur.execute("""
    SELECT id_mapa
    FROM mapa_competitivo_cliente
    WHERE id_cliente = ?
      AND id_producto_cliente = ?
      AND id_producto_competidor_fuente = ?
      AND rol_competidor = ?
      AND activo = 1
    """, (
        id_cliente,
        id_producto_cliente,
        data.id_producto_competidor_fuente,
        rol
    ))

    existente = cur.fetchone()

    if existente:
        conn.close()
        return {
            "ok": True,
            "mensaje": "El competidor ya estaba asociado con ese rol.",
            "id_mapa": existente["id_mapa"],
            "competidor": competidor
        }

    cur.execute("""
    INSERT INTO mapa_competitivo_cliente (
        id_cliente,
        id_producto_cliente,
        id_producto_competidor_fuente,
        ean_competidor,
        nombre_competidor,
        marca_competidor,
        retailer_competidor,
        categoria_competidor,
        rol_competidor,
        margen_esperado_pct,
        brecha_minima_pct,
        brecha_maxima_pct,
        comentario_estrategia,
        activo
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
    """, (
        id_cliente,
        id_producto_cliente,
        data.id_producto_competidor_fuente,
        competidor.get("ean"),
        competidor.get("nombre_producto"),
        competidor.get("marca"),
        competidor.get("retailer"),
        competidor.get("categoria"),
        rol,
        data.margen_esperado_pct,
        data.brecha_minima_pct,
        data.brecha_maxima_pct,
        data.comentario_estrategia
    ))

    id_mapa = cur.lastrowid
    conn.commit()
    conn.close()

    return {
        "ok": True,
        "mensaje": "Competidor asociado correctamente.",
        "id_mapa": id_mapa,
        "producto_propio": dict(producto_propio),
        "competidor": competidor,
        "rol_competidor": rol,
        "estrategia": {
            "margen_esperado_pct": data.margen_esperado_pct,
            "brecha_minima_pct": data.brecha_minima_pct,
            "brecha_maxima_pct": data.brecha_maxima_pct,
            "comentario_estrategia": data.comentario_estrategia
        }
    }


@app.get("/clientes/{id_cliente}/productos-propios/{id_producto_cliente}/competidores")
def listar_competidores_producto(id_cliente: int, id_producto_cliente: int):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Producto propio
    cur.execute("""
    SELECT
        pc.id_producto_cliente,
        pc.id_producto_fuente,
        pc.nombre_producto,
        pc.marca,
        pc.ean,
        pc.retailer,
        pc.categoria,
        cp.precio_actual,
        cp.precio_regular,
        cp.precio_oferta,
        cp.tipo_promocion,
        cp.disponibilidad,
        pf.url_producto
    FROM productos_cliente pc
    LEFT JOIN productos_fuente pf
        ON pf.id_producto_fuente = pc.id_producto_fuente
    LEFT JOIN capturas_precio cp
        ON cp.id_producto_fuente = pc.id_producto_fuente
    WHERE pc.id_cliente = ?
      AND pc.id_producto_cliente = ?
      AND pc.activo = 1
    """, (id_cliente, id_producto_cliente))

    producto = cur.fetchone()

    if not producto:
        conn.close()
        return {
            "encontrado": False,
            "error": "Producto propio no encontrado o inactivo.",
            "competidores": []
        }

    producto = dict(producto)

    cur.execute("""
    SELECT
        mc.id_mapa,
        mc.id_cliente,
        mc.id_producto_cliente,
        mc.id_producto_competidor_fuente,
        mc.ean_competidor,
        mc.nombre_competidor,
        mc.marca_competidor,
        mc.retailer_competidor,
        mc.categoria_competidor,
        mc.rol_competidor,
        mc.margen_esperado_pct,
        mc.brecha_minima_pct,
        mc.brecha_maxima_pct,
        mc.comentario_estrategia,
        mc.activo,
        mc.fecha_alta,
        cp.precio_actual,
        cp.precio_regular,
        cp.precio_oferta,
        cp.tipo_promocion,
        cp.disponibilidad,
        pf.url_producto,
        pf.url_imagen
    FROM mapa_competitivo_cliente mc
    LEFT JOIN productos_fuente pf
        ON pf.id_producto_fuente = mc.id_producto_competidor_fuente
    LEFT JOIN capturas_precio cp
        ON cp.id_producto_fuente = mc.id_producto_competidor_fuente
    WHERE mc.id_cliente = ?
      AND mc.id_producto_cliente = ?
      AND mc.activo = 1
    ORDER BY
        CASE mc.rol_competidor
            WHEN 'COMPETIDOR_DIRECTO' THEN 1
            WHEN 'LIDER_CATEGORIA' THEN 2
            WHEN 'ALTERNATIVA_ECONOMICA' THEN 3
            WHEN 'MARCA_PROPIA' THEN 4
            WHEN 'SUSTITUTO' THEN 5
            ELSE 99
        END,
        mc.fecha_alta DESC
    """, (id_cliente, id_producto_cliente))

    competidores = [dict(r) for r in cur.fetchall()]
    conn.close()

    return {
        "encontrado": True,
        "producto_propio": producto,
        "total_competidores": len(competidores),
        "competidores": competidores
    }


@app.delete("/clientes/{id_cliente}/competidores/{id_mapa}")
def eliminar_competidor(id_cliente: int, id_mapa: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
    SELECT id_mapa
    FROM mapa_competitivo_cliente
    WHERE id_cliente = ?
      AND id_mapa = ?
      AND activo = 1
    """, (id_cliente, id_mapa))

    row = cur.fetchone()

    if not row:
        conn.close()
        return {
            "ok": False,
            "error": "Competidor no encontrado o ya estaba inactivo."
        }

    cur.execute("""
    UPDATE mapa_competitivo_cliente
    SET activo = 0
    WHERE id_cliente = ?
      AND id_mapa = ?
    """, (id_cliente, id_mapa))

    conn.commit()
    conn.close()

    return {
        "ok": True,
        "mensaje": "Competidor desactivado correctamente."
    }


@app.get("/roles-competidor")
def listar_roles_competidor():
    return {
        "roles": [
            {
                "codigo": "COMPETIDOR_DIRECTO",
                "nombre": "Competidor directo",
                "descripcion": "Producto que compite directamente contra el producto propio."
            },
            {
                "codigo": "LIDER_CATEGORIA",
                "nombre": "Líder de categoría",
                "descripcion": "Marca o producto referente de la categoría."
            },
            {
                "codigo": "ALTERNATIVA_ECONOMICA",
                "nombre": "Alternativa económica",
                "descripcion": "Producto de menor precio usado como referencia defensiva."
            },
            {
                "codigo": "MARCA_PROPIA",
                "nombre": "Marca propia",
                "descripcion": "Producto de marca propia del retailer."
            },
            {
                "codigo": "SUSTITUTO",
                "nombre": "Sustituto",
                "descripcion": "Producto que no es igual, pero puede reemplazar la compra."
            },
        ]
    }



# ============================================================
# RESUMEN EJECUTIVO DE PRICING POR CLIENTE
# ============================================================

@app.get("/clientes/{id_cliente}/resumen-pricing")
def resumen_pricing_cliente(id_cliente: int):
    resultado = analizar_pricing_cliente(id_cliente)

    if not resultado.get("ok"):
        return resultado

    cliente = resultado.get("cliente")
    analisis = resultado.get("analisis", [])

    productos_propios_ids = set()
    competidores_ids = set()

    alertas_altas = 0
    alertas_medias = 0
    alertas_bajas = 0
    alertas_monitoreo = 0

    competidores_en_oferta = 0
    productos_propios_en_oferta = 0
    ambos_en_oferta = 0

    fuera_de_rango = 0
    posicionamiento_ok = 0
    sin_stock_propio = 0
    sin_precio_propio = 0

    brechas = []
    brechas_positivas = []
    brechas_negativas = []

    resumen_por_alerta = {}
    resumen_por_rol = {}
    resumen_por_retailer_propio = {}
    resumen_por_retailer_competidor = {}

    top_alertas_altas = []
    top_competidores_en_oferta = []
    top_sobreprecio = []
    top_oportunidad_margen = []

    for item in analisis:
        id_producto_cliente = item.get("id_producto_cliente")
        id_mapa = item.get("id_mapa")

        if id_producto_cliente is not None:
            productos_propios_ids.add(id_producto_cliente)

        if id_mapa is not None:
            competidores_ids.add(id_mapa)

        alerta = item.get("alerta") or "SIN_ALERTA"
        prioridad = item.get("prioridad") or "SIN_PRIORIDAD"
        rol = item.get("rol_competidor") or "SIN_ROL"
        retailer_propio = item.get("retailer_propio") or "SIN_RETAILER"
        retailer_comp = item.get("retailer_competidor") or "SIN_RETAILER"

        resumen_por_alerta[alerta] = resumen_por_alerta.get(alerta, 0) + 1
        resumen_por_rol[rol] = resumen_por_rol.get(rol, 0) + 1
        resumen_por_retailer_propio[retailer_propio] = resumen_por_retailer_propio.get(retailer_propio, 0) + 1
        resumen_por_retailer_competidor[retailer_comp] = resumen_por_retailer_competidor.get(retailer_comp, 0) + 1

        if prioridad == "ALTA":
            alertas_altas += 1
            top_alertas_altas.append(item)
        elif prioridad == "MEDIA":
            alertas_medias += 1
        elif prioridad == "BAJA":
            alertas_bajas += 1
        elif prioridad == "MONITOREO":
            alertas_monitoreo += 1

        if item.get("competidor_en_oferta"):
            competidores_en_oferta += 1
            top_competidores_en_oferta.append(item)

        if item.get("producto_propio_en_oferta"):
            productos_propios_en_oferta += 1

        if item.get("competidor_en_oferta") and item.get("producto_propio_en_oferta"):
            ambos_en_oferta += 1

        if alerta in {
            "SOBREPRECIO_FUERA_DE_RANGO",
            "COMPETIDOR_EN_OFERTA_SIN_RESPUESTA_PROPIA",
        }:
            fuera_de_rango += 1
            top_sobreprecio.append(item)

        if alerta in {
            "POSICIONAMIENTO_OK",
            "POSICIONAMIENTO_OK_VS_LIDER",
            "POSICIONAMIENTO_OK_VS_ALTERNATIVA_ECONOMICA",
            "POSICIONAMIENTO_OK_VS_MARCA_PROPIA",
        }:
            posicionamiento_ok += 1

        if alerta == "PRODUCTO_PROPIO_SIN_STOCK":
            sin_stock_propio += 1

        if alerta == "PRODUCTO_PROPIO_SIN_PRECIO":
            sin_precio_propio += 1

        if alerta == "BRECHA_INSUFICIENTE_O_PRECIO_BAJO":
            top_oportunidad_margen.append(item)

        brecha = item.get("brecha_actual_%")
        if brecha is not None:
            try:
                brecha = float(brecha)
                brechas.append(brecha)
                if brecha > 0:
                    brechas_positivas.append(brecha)
                elif brecha < 0:
                    brechas_negativas.append(brecha)
            except Exception:
                pass

    def promedio(lista):
        if not lista:
            return None
        return round(sum(lista) / len(lista), 2)

    def ordenar_por_brecha_abs(items, limit=10):
        def key_func(x):
            b = x.get("brecha_actual_%")
            try:
                return abs(float(b)) if b is not None else 0
            except Exception:
                return 0

        return sorted(items, key=key_func, reverse=True)[:limit]

    def simplificar_item(item):
        return {
            "id_producto_cliente": item.get("id_producto_cliente"),
            "producto_propio": item.get("producto_propio"),
            "retailer_propio": item.get("retailer_propio"),
            "precio_propio_actual": item.get("precio_propio_actual"),
            "competidor": item.get("competidor"),
            "retailer_competidor": item.get("retailer_competidor"),
            "rol_competidor": item.get("rol_competidor"),
            "precio_competidor_actual": item.get("precio_competidor_actual"),
            "competidor_en_oferta": item.get("competidor_en_oferta"),
            "producto_propio_en_oferta": item.get("producto_propio_en_oferta"),
            "brecha_actual_%": item.get("brecha_actual_%"),
            "brecha_actual_$": item.get("brecha_actual_$"),
            "brecha_minima_pct": item.get("brecha_minima_pct"),
            "brecha_maxima_pct": item.get("brecha_maxima_pct"),
            "alerta": item.get("alerta"),
            "prioridad": item.get("prioridad"),
            "accion_sugerida": item.get("accion_sugerida"),
        }

    top_alertas_altas = [simplificar_item(x) for x in ordenar_por_brecha_abs(top_alertas_altas, 10)]
    top_competidores_en_oferta = [simplificar_item(x) for x in ordenar_por_brecha_abs(top_competidores_en_oferta, 10)]
    top_sobreprecio = [simplificar_item(x) for x in ordenar_por_brecha_abs(top_sobreprecio, 10)]
    top_oportunidad_margen = [simplificar_item(x) for x in ordenar_por_brecha_abs(top_oportunidad_margen, 10)]

    total_relaciones = len(analisis)

    if total_relaciones > 0:
        pct_alertas_altas = round(alertas_altas / total_relaciones * 100, 2)
        pct_fuera_de_rango = round(fuera_de_rango / total_relaciones * 100, 2)
        pct_posicionamiento_ok = round(posicionamiento_ok / total_relaciones * 100, 2)
        pct_competidores_en_oferta = round(competidores_en_oferta / total_relaciones * 100, 2)
    else:
        pct_alertas_altas = 0
        pct_fuera_de_rango = 0
        pct_posicionamiento_ok = 0
        pct_competidores_en_oferta = 0

    return {
        "ok": True,
        "cliente": cliente,
        "cards": {
            "productos_propios_monitoreados": len(productos_propios_ids),
            "competidores_asociados": len(competidores_ids),
            "relaciones_analizadas": total_relaciones,
            "alertas_altas": alertas_altas,
            "alertas_medias": alertas_medias,
            "alertas_bajas": alertas_bajas,
            "alertas_monitoreo": alertas_monitoreo,
            "competidores_en_oferta": competidores_en_oferta,
            "productos_propios_en_oferta": productos_propios_en_oferta,
            "ambos_en_oferta": ambos_en_oferta,
            "fuera_de_rango": fuera_de_rango,
            "posicionamiento_ok": posicionamiento_ok,
            "productos_propios_sin_stock": sin_stock_propio,
            "productos_propios_sin_precio": sin_precio_propio,
            "brecha_promedio_pct": promedio(brechas),
            "brecha_promedio_cuando_mas_caro_pct": promedio(brechas_positivas),
            "brecha_promedio_cuando_mas_barato_pct": promedio(brechas_negativas),
        },
        "porcentajes": {
            "pct_alertas_altas": pct_alertas_altas,
            "pct_fuera_de_rango": pct_fuera_de_rango,
            "pct_posicionamiento_ok": pct_posicionamiento_ok,
            "pct_competidores_en_oferta": pct_competidores_en_oferta,
        },
        "resumen_por_alerta": resumen_por_alerta,
        "resumen_por_rol": resumen_por_rol,
        "resumen_por_retailer_propio": resumen_por_retailer_propio,
        "resumen_por_retailer_competidor": resumen_por_retailer_competidor,
        "top": {
            "alertas_altas": top_alertas_altas,
            "competidores_en_oferta": top_competidores_en_oferta,
            "sobreprecio_fuera_de_rango": top_sobreprecio,
            "oportunidad_capturar_margen": top_oportunidad_margen,
        }
    }



# ============================================================
# CATEGORÍAS RELEVANTES POR CLIENTE
# ============================================================

PRIORIDADES_CATEGORIA_VALIDAS = {"alta", "media", "baja"}


@app.get("/clientes/{id_cliente}/categorias-relevantes")
def listar_categorias_relevantes(id_cliente: int):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
    SELECT id_cliente, nombre_cliente, rubro, estado
    FROM clientes
    WHERE id_cliente = ?
    """, (id_cliente,))

    cliente = cur.fetchone()

    if not cliente:
        conn.close()
        return {
            "ok": False,
            "error": "Cliente no encontrado.",
            "categorias": []
        }

    cur.execute("""
    SELECT
        id_categoria_cliente,
        id_cliente,
        retailer,
        categoria,
        categoria_id,
        prioridad,
        activa,
        fecha_alta
    FROM categorias_cliente
    WHERE id_cliente = ?
      AND activa = 1
    ORDER BY
        CASE prioridad
            WHEN 'alta' THEN 1
            WHEN 'media' THEN 2
            WHEN 'baja' THEN 3
            ELSE 99
        END,
        retailer,
        categoria
    """, (id_cliente,))

    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    return {
        "ok": True,
        "cliente": dict(cliente),
        "total": len(rows),
        "categorias": rows
    }


@app.post("/clientes/{id_cliente}/categorias-relevantes")
def agregar_categoria_relevante(id_cliente: int, data: CategoriaClienteCreate):
    retailer = data.retailer.strip().lower()
    categoria = data.categoria.strip()
    prioridad = (data.prioridad or "media").strip().lower()

    if not retailer:
        return {
            "ok": False,
            "error": "El retailer es obligatorio."
        }

    if not categoria:
        return {
            "ok": False,
            "error": "La categoría es obligatoria."
        }

    if prioridad not in PRIORIDADES_CATEGORIA_VALIDAS:
        return {
            "ok": False,
            "error": "Prioridad inválida.",
            "prioridades_validas": sorted(list(PRIORIDADES_CATEGORIA_VALIDAS))
        }

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Validar cliente
    cur.execute("""
    SELECT id_cliente, nombre_cliente, rubro, estado
    FROM clientes
    WHERE id_cliente = ?
      AND estado = 'activo'
    """, (id_cliente,))

    cliente = cur.fetchone()

    if not cliente:
        conn.close()
        return {
            "ok": False,
            "error": "Cliente no encontrado o inactivo."
        }

    # Evitar duplicado activo
    cur.execute("""
    SELECT id_categoria_cliente
    FROM categorias_cliente
    WHERE id_cliente = ?
      AND lower(retailer) = lower(?)
      AND lower(categoria) = lower(?)
      AND activa = 1
    """, (id_cliente, retailer, categoria))

    existente = cur.fetchone()

    if existente:
        conn.close()
        return {
            "ok": True,
            "mensaje": "La categoría relevante ya estaba activa para este cliente.",
            "id_categoria_cliente": existente["id_categoria_cliente"]
        }

    cur.execute("""
    INSERT INTO categorias_cliente (
        id_cliente,
        retailer,
        categoria,
        categoria_id,
        prioridad,
        activa
    )
    VALUES (?, ?, ?, ?, ?, 1)
    """, (
        id_cliente,
        retailer,
        categoria,
        data.categoria_id,
        prioridad
    ))

    id_categoria_cliente = cur.lastrowid
    conn.commit()

    cur.execute("""
    SELECT
        id_categoria_cliente,
        id_cliente,
        retailer,
        categoria,
        categoria_id,
        prioridad,
        activa,
        fecha_alta
    FROM categorias_cliente
    WHERE id_categoria_cliente = ?
    """, (id_categoria_cliente,))

    row = dict(cur.fetchone())
    conn.close()

    return {
        "ok": True,
        "mensaje": "Categoría relevante agregada correctamente.",
        "categoria": row
    }


@app.delete("/clientes/{id_cliente}/categorias-relevantes/{id_categoria_cliente}")
def eliminar_categoria_relevante(id_cliente: int, id_categoria_cliente: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
    SELECT id_categoria_cliente
    FROM categorias_cliente
    WHERE id_cliente = ?
      AND id_categoria_cliente = ?
      AND activa = 1
    """, (id_cliente, id_categoria_cliente))

    row = cur.fetchone()

    if not row:
        conn.close()
        return {
            "ok": False,
            "error": "Categoría relevante no encontrada o ya estaba inactiva."
        }

    cur.execute("""
    UPDATE categorias_cliente
    SET activa = 0
    WHERE id_cliente = ?
      AND id_categoria_cliente = ?
    """, (id_cliente, id_categoria_cliente))

    conn.commit()
    conn.close()

    return {
        "ok": True,
        "mensaje": "Categoría relevante desactivada correctamente."
    }


@app.get("/catalogo/categorias")
def listar_categorias_catalogo(
    retailer: Optional[str] = Query(None, description="Filtrar por retailer: coto, dia, changomas"),
    solo_con_productos_disponibles: bool = Query(False)
):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    sql = """
    SELECT
        pf.retailer,
        pf.categoria_original AS categoria,
        COUNT(*) AS productos_totales,
        SUM(CASE WHEN cp.precio_actual IS NOT NULL THEN 1 ELSE 0 END) AS productos_con_precio,
        SUM(CASE WHEN COALESCE(cp.disponibilidad, 0) = 1 THEN 1 ELSE 0 END) AS productos_disponibles
    FROM productos_fuente pf
    LEFT JOIN capturas_precio cp
        ON cp.id_producto_fuente = pf.id_producto_fuente
    WHERE pf.categoria_original IS NOT NULL
    """

    params = []

    if retailer:
        sql += " AND lower(pf.retailer) = ?"
        params.append(retailer.lower())

    if solo_con_productos_disponibles:
        sql += " AND COALESCE(cp.disponibilidad, 0) = 1 AND cp.precio_actual IS NOT NULL"

    sql += """
    GROUP BY pf.retailer, pf.categoria_original
    ORDER BY pf.retailer, pf.categoria_original
    """

    cur.execute(sql, params)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    return {
        "total": len(rows),
        "categorias": rows
    }



# ============================================================
# SUGERENCIA AUTOMÁTICA DE CATEGORÍAS RELEVANTES
# ============================================================

def _normalizar_categoria_texto(txt):
    if txt is None:
        return ""
    txt = str(txt).lower().strip()
    reemplazos = {
        "á": "a",
        "é": "e",
        "í": "i",
        "ó": "o",
        "ú": "u",
        "ñ": "n",
    }
    for a, b in reemplazos.items():
        txt = txt.replace(a, b)
    return txt


def _inferir_prioridad_categoria(categoria, cantidad_productos_propios, productos_disponibles_catalogo):
    cat = _normalizar_categoria_texto(categoria)

    # Categorías normalmente muy relevantes para consumo masivo
    keywords_alta = [
        "limpieza",
        "perfumeria",
        "bebidas",
        "almacen",
        "lacteos",
        "quesos",
        "snacks",
        "desayuno",
        "aceites",
        "arroz",
        "conservas",
        "condimentos",
        "mascotas",
        "bebes",
        "cuidado",
    ]

    if cantidad_productos_propios >= 2:
        return "alta"

    if any(k in cat for k in keywords_alta):
        return "alta"

    if productos_disponibles_catalogo and productos_disponibles_catalogo >= 100:
        return "media"

    return "baja"


@app.get("/clientes/{id_cliente}/sugerir-categorias")
def sugerir_categorias_cliente(id_cliente: int):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Validar cliente
    cur.execute("""
    SELECT id_cliente, nombre_cliente, rubro, estado
    FROM clientes
    WHERE id_cliente = ?
    """, (id_cliente,))

    cliente = cur.fetchone()

    if not cliente:
        conn.close()
        return {
            "ok": False,
            "error": "Cliente no encontrado.",
            "sugerencias": []
        }

    cliente = dict(cliente)

    # Productos propios activos del cliente
    cur.execute("""
    SELECT
        pc.id_producto_cliente,
        pc.id_producto_fuente,
        pc.nombre_producto,
        pc.marca,
        pc.ean,
        pc.retailer,
        pc.categoria
    FROM productos_cliente pc
    WHERE pc.id_cliente = ?
      AND pc.activo = 1
    """, (id_cliente,))

    productos = [dict(r) for r in cur.fetchall()]

    if not productos:
        conn.close()
        return {
            "ok": True,
            "cliente": cliente,
            "mensaje": "El cliente todavía no tiene productos propios seleccionados. No hay categorías para sugerir.",
            "total_sugerencias": 0,
            "sugerencias": []
        }

    # Categorías ya activas para no repetirlas
    cur.execute("""
    SELECT
        lower(retailer) AS retailer,
        lower(categoria) AS categoria
    FROM categorias_cliente
    WHERE id_cliente = ?
      AND activa = 1
    """, (id_cliente,))

    categorias_activas = {
        (r["retailer"], r["categoria"])
        for r in cur.fetchall()
    }

    # Agrupar categorías de los productos propios
    base_sugerencias = {}

    for p in productos:
        retailer = (p.get("retailer") or "").lower()
        categoria = p.get("categoria") or "SIN_CATEGORIA"

        key = (retailer, categoria)

        if key not in base_sugerencias:
            base_sugerencias[key] = {
                "retailer": retailer,
                "categoria": categoria,
                "productos_propios_detectados": 0,
                "productos_propios_ejemplo": []
            }

        base_sugerencias[key]["productos_propios_detectados"] += 1

        if len(base_sugerencias[key]["productos_propios_ejemplo"]) < 5:
            base_sugerencias[key]["productos_propios_ejemplo"].append({
                "id_producto_cliente": p.get("id_producto_cliente"),
                "nombre_producto": p.get("nombre_producto"),
                "marca": p.get("marca"),
                "ean": p.get("ean")
            })

    sugerencias = []

    for (retailer, categoria), data in base_sugerencias.items():
        # Medir tamaño de categoría en catálogo
        cur.execute("""
        SELECT
            COUNT(*) AS productos_totales,
            SUM(CASE WHEN cp.precio_actual IS NOT NULL THEN 1 ELSE 0 END) AS productos_con_precio,
            SUM(CASE WHEN COALESCE(cp.disponibilidad, 0) = 1 THEN 1 ELSE 0 END) AS productos_disponibles
        FROM productos_fuente pf
        LEFT JOIN capturas_precio cp
            ON cp.id_producto_fuente = pf.id_producto_fuente
        WHERE lower(pf.retailer) = lower(?)
          AND lower(COALESCE(pf.categoria_original, '')) = lower(?)
        """, (retailer, categoria))

        stats = dict(cur.fetchone())

        productos_disponibles = stats.get("productos_disponibles") or 0

        prioridad = _inferir_prioridad_categoria(
            categoria,
            data["productos_propios_detectados"],
            productos_disponibles
        )

        ya_activa = (retailer.lower(), categoria.lower()) in categorias_activas

        sugerencias.append({
            "retailer": retailer,
            "categoria": categoria,
            "categoria_id": None,
            "prioridad_sugerida": prioridad,
            "ya_activa": ya_activa,
            "motivo": "Categoría detectada automáticamente a partir de productos propios seleccionados.",
            "productos_propios_detectados": data["productos_propios_detectados"],
            "productos_propios_ejemplo": data["productos_propios_ejemplo"],
            "catalogo": {
                "productos_totales": stats.get("productos_totales") or 0,
                "productos_con_precio": stats.get("productos_con_precio") or 0,
                "productos_disponibles": productos_disponibles
            }
        })

    # Orden ejecutivo
    orden_prioridad = {"alta": 1, "media": 2, "baja": 3}
    sugerencias = sorted(
        sugerencias,
        key=lambda x: (
            x["ya_activa"],
            orden_prioridad.get(x["prioridad_sugerida"], 99),
            x["retailer"],
            x["categoria"]
        )
    )

    conn.close()

    return {
        "ok": True,
        "cliente": cliente,
        "total_productos_propios": len(productos),
        "total_sugerencias": len(sugerencias),
        "sugerencias": sugerencias
    }



# ============================================================
# ACTIVAR CATEGORÍAS SUGERIDAS EN LOTE
# ============================================================

@app.post("/clientes/{id_cliente}/categorias-relevantes/activar-sugeridas")
def activar_categorias_sugeridas(id_cliente: int):
    """
    Activa automáticamente las categorías sugeridas por JUSTO
    a partir de los productos propios seleccionados por el cliente.
    Evita duplicados y solo inserta categorías que todavía no estén activas.
    """

    sugerencias_resultado = sugerir_categorias_cliente(id_cliente)

    if not sugerencias_resultado.get("ok"):
        return sugerencias_resultado

    sugerencias = sugerencias_resultado.get("sugerencias", [])

    if not sugerencias:
        return {
            "ok": True,
            "mensaje": "No hay categorías sugeridas para activar.",
            "categorias_activadas": [],
            "categorias_ya_activas": [],
            "total_activadas": 0,
            "total_ya_activas": 0
        }

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Validar cliente activo
    cur.execute("""
    SELECT id_cliente, nombre_cliente, rubro, estado
    FROM clientes
    WHERE id_cliente = ?
      AND estado = 'activo'
    """, (id_cliente,))

    cliente = cur.fetchone()

    if not cliente:
        conn.close()
        return {
            "ok": False,
            "error": "Cliente no encontrado o inactivo."
        }

    categorias_activadas = []
    categorias_ya_activas = []

    for s in sugerencias:
        retailer = (s.get("retailer") or "").strip().lower()
        categoria = (s.get("categoria") or "").strip()
        categoria_id = s.get("categoria_id")
        prioridad = (s.get("prioridad_sugerida") or "media").strip().lower()

        if not retailer or not categoria:
            continue

        cur.execute("""
        SELECT
            id_categoria_cliente,
            retailer,
            categoria,
            categoria_id,
            prioridad,
            activa
        FROM categorias_cliente
        WHERE id_cliente = ?
          AND lower(retailer) = lower(?)
          AND lower(categoria) = lower(?)
          AND activa = 1
        """, (id_cliente, retailer, categoria))

        existente = cur.fetchone()

        if existente:
            categorias_ya_activas.append(dict(existente))
            continue

        cur.execute("""
        INSERT INTO categorias_cliente (
            id_cliente,
            retailer,
            categoria,
            categoria_id,
            prioridad,
            activa
        )
        VALUES (?, ?, ?, ?, ?, 1)
        """, (
            id_cliente,
            retailer,
            categoria,
            categoria_id,
            prioridad
        ))

        id_categoria_cliente = cur.lastrowid

        cur.execute("""
        SELECT
            id_categoria_cliente,
            id_cliente,
            retailer,
            categoria,
            categoria_id,
            prioridad,
            activa,
            fecha_alta
        FROM categorias_cliente
        WHERE id_categoria_cliente = ?
        """, (id_categoria_cliente,))

        categorias_activadas.append(dict(cur.fetchone()))

    conn.commit()
    conn.close()

    return {
        "ok": True,
        "mensaje": "Categorías sugeridas procesadas correctamente.",
        "cliente": sugerencias_resultado.get("cliente"),
        "total_sugerencias": len(sugerencias),
        "total_activadas": len(categorias_activadas),
        "total_ya_activas": len(categorias_ya_activas),
        "categorias_activadas": categorias_activadas,
        "categorias_ya_activas": categorias_ya_activas
    }

