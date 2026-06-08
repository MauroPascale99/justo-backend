# Supabase migration plan

## Tablas principales futuras

- clientes
- usuarios_cliente
- planes
- suscripciones_cliente
- retailers_cliente
- categorias_cliente
- productos_fuente
- capturas_precio
- productos_cliente
- producto_cliente_retailer_detalle
- mapa_competitivo_cliente
- configuracion_pricing_cliente
- oportunidades_historicas
- onboarding_cliente

## Principio de seguridad

Cada tabla privada debe tener id_cliente.
En Supabase se deben aplicar políticas RLS para que cada usuario vea solo datos de su cliente.

## Mis Productos

El alta debe ser por EAN agrupado, no por producto-retailer.

## Pricing

Precio regular = base de comparación.
Precio oferta = dato complementario.
