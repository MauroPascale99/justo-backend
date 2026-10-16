-- Equipo compartido de ejecución: domicilios operativos, asignaciones y estado de visita.
-- Todos los usuarios del mismo cliente ven y administran el mismo tablero.

BEGIN;

CREATE TABLE IF NOT EXISTS public.equipo_cobertura (
    id_integrante bigserial PRIMARY KEY,
    id_cliente integer NOT NULL REFERENCES public.clientes(id_cliente) ON DELETE CASCADE,
    nombre text NOT NULL CHECK (length(trim(nombre)) BETWEEN 2 AND 120),
    provincia text,
    localidad text,
    direccion text,
    latitud numeric(10, 7),
    longitud numeric(10, 7),
    activo boolean NOT NULL DEFAULT true,
    creado_en timestamp with time zone NOT NULL DEFAULT now(),
    actualizado_en timestamp with time zone NOT NULL DEFAULT now(),
    UNIQUE (id_cliente, nombre)
);

CREATE TABLE IF NOT EXISTS public.equipo_asignaciones_cobertura (
    id_asignacion bigserial PRIMARY KEY,
    id_cliente integer NOT NULL REFERENCES public.clientes(id_cliente) ON DELETE CASCADE,
    id_integrante bigint NOT NULL REFERENCES public.equipo_cobertura(id_integrante) ON DELETE CASCADE,
    clave_sucursal text NOT NULL REFERENCES public.cobertura_sucursales(clave) ON DELETE CASCADE,
    estado text NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente', 'visitada', 'incidencia')),
    observacion text,
    asignado_en timestamp with time zone NOT NULL DEFAULT now(),
    actualizado_en timestamp with time zone NOT NULL DEFAULT now(),
    UNIQUE (id_cliente, clave_sucursal)
);

CREATE INDEX IF NOT EXISTS idx_equipo_cobertura_cliente ON public.equipo_cobertura (id_cliente, activo, nombre);
CREATE INDEX IF NOT EXISTS idx_equipo_asignaciones_integrante ON public.equipo_asignaciones_cobertura (id_integrante, estado);

ALTER TABLE public.equipo_cobertura ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.equipo_asignaciones_cobertura ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS equipo_cobertura_compartido_cliente ON public.equipo_cobertura;
CREATE POLICY equipo_cobertura_compartido_cliente ON public.equipo_cobertura
    FOR ALL TO authenticated
    USING (id_cliente = get_id_cliente())
    WITH CHECK (id_cliente = get_id_cliente());

DROP POLICY IF EXISTS equipo_asignaciones_compartidas_cliente ON public.equipo_asignaciones_cobertura;
CREATE POLICY equipo_asignaciones_compartidas_cliente ON public.equipo_asignaciones_cobertura
    FOR ALL TO authenticated
    USING (id_cliente = get_id_cliente())
    WITH CHECK (id_cliente = get_id_cliente());

COMMIT;
