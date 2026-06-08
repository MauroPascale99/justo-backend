# JUSTO Pricing 360

JUSTO Pricing 360 es un SaaS universal de inteligencia competitiva de precios para proveedores/marcas que venden en retailers.

## Regla estratégica

NO desarrollar para Ecovita hardcodeado.
Ecovita es solo cliente de prueba local: id_cliente=1.

Toda lógica debe ser universal y parametrizada por:
- id_cliente
- plan
- retailers habilitados
- marcas/productos configurados
- productos propios agrupados por EAN
- competidores agrupados por EAN
- configuración privada de pricing por cliente

## Reglas de producto

1. Mis Productos no trabaja por producto-retailer.
   Trabaja por producto normalizado, idealmente EAN.

2. Un producto propio = un EAN agrupado.
   Dentro del producto se muestran los precios por retailer.

3. La comparación principal usa precio regular.
   El precio oferta se muestra aparte como dato secundario.

4. La categoría del cliente es contexto comercial y límite de plan.
   No debe bloquear la búsqueda de productos propios.

5. La captura universal por categorías sirve para radar general.
   La captura dirigida por marca/producto sirve para onboarding y Mis Productos.

6. El dashboard privado debe estar aislado por id_cliente.

## Estado actual

Backend local-first con SQLite.
Próximo destino: Vercel + Supabase.

## Próximo paso

Convertir el prototipo local de Mis Productos en frontend modular y luego migrar datos a Supabase.

## Scripts reconstruidos durante limpieza

Se reconstruyeron en backend/scripts:

- agregar_producto_agrupado_cliente.py
  Alta de producto propio por EAN agrupado.
  Usa ultima_busqueda_mis_productos_agrupada.csv.
  Guarda producto como MULTI_RETAILER.

- guardar_competidor_directo_cliente.py
  Versión base para guardar competidor directo.
  Pendiente evolucionar a competidor agrupado por EAN.

