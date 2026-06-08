-- =============================================================================
-- 004_enable_rls_supabase.sql
-- Activa Row Level Security en las 9 tablas que el advisor de Supabase marca
-- como EXPUESTAS (RLS desactivado, accesibles con la anon key).
--
-- Convencion existente (no la cambiamos): tablas con id_cliente usan
--   USING (id_cliente = get_id_cliente())
-- donde get_id_cliente() = SELECT id_cliente FROM usuarios_cliente
--                          WHERE auth_user_id = auth.uid() LIMIT 1
--
-- Estrategia por tipo de tabla:
--  * Compartidas de scraping (sin id_cliente) que el FRONTEND lee con la
--    sesion del usuario -> RLS + SELECT solo para rol authenticated.
--    Las escrituras siguen por el pipeline Python via DATABASE_URL
--    (rol postgres), que IGNORA RLS, asi que el scraping no se ve afectado.
--  * Internas (auditoria_capturas) que el frontend NO lee -> RLS sin policy
--    (solo postgres/service_role).
--  * Client-scoped (conversaciones_ia, reportes_generados, mensajes_ia)
--    -> policy por cliente, igual que el resto del esquema.
--
-- Idempotente: se puede correr varias veces.
-- Para revertir, ver el bloque ROLLBACK comentado al final.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- 1) Tablas COMPARTIDAS de scraping: lectura para usuarios logueados.
--    (El frontend lee productos_fuente y capturas_precio con la anon key +
--     sesion; fuentes/planes/eventos_precio se incluyen por las dudas y porque
--     no son datos confidenciales por cliente.)
-- -----------------------------------------------------------------------------
ALTER TABLE public.productos_fuente ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS productos_fuente_select_auth ON public.productos_fuente;
CREATE POLICY productos_fuente_select_auth ON public.productos_fuente
    FOR SELECT TO authenticated USING (true);

ALTER TABLE public.capturas_precio ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS capturas_precio_select_auth ON public.capturas_precio;
CREATE POLICY capturas_precio_select_auth ON public.capturas_precio
    FOR SELECT TO authenticated USING (true);

ALTER TABLE public.fuentes ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS fuentes_select_auth ON public.fuentes;
CREATE POLICY fuentes_select_auth ON public.fuentes
    FOR SELECT TO authenticated USING (true);

ALTER TABLE public.planes ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS planes_select_auth ON public.planes;
CREATE POLICY planes_select_auth ON public.planes
    FOR SELECT TO authenticated USING (true);

ALTER TABLE public.eventos_precio ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS eventos_precio_select_auth ON public.eventos_precio;
CREATE POLICY eventos_precio_select_auth ON public.eventos_precio
    FOR SELECT TO authenticated USING (true);

-- -----------------------------------------------------------------------------
-- 2) Tabla INTERNA de auditoria: RLS activo, SIN policy.
--    Solo accesible por postgres/service_role (que ignoran RLS).
-- -----------------------------------------------------------------------------
ALTER TABLE public.auditoria_capturas ENABLE ROW LEVEL SECURITY;

-- -----------------------------------------------------------------------------
-- 3) Tablas CLIENT-SCOPED: aislamiento por cliente (misma convencion).
-- -----------------------------------------------------------------------------
ALTER TABLE public.conversaciones_ia ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS conversaciones_ia_solo_su_cliente ON public.conversaciones_ia;
CREATE POLICY conversaciones_ia_solo_su_cliente ON public.conversaciones_ia
    FOR ALL USING (id_cliente = get_id_cliente());

ALTER TABLE public.reportes_generados ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS reportes_generados_solo_su_cliente ON public.reportes_generados;
CREATE POLICY reportes_generados_solo_su_cliente ON public.reportes_generados
    FOR ALL USING (id_cliente = get_id_cliente());

-- mensajes_ia no tiene id_cliente: se valida via la conversacion padre.
ALTER TABLE public.mensajes_ia ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS mensajes_ia_solo_su_cliente ON public.mensajes_ia;
CREATE POLICY mensajes_ia_solo_su_cliente ON public.mensajes_ia
    FOR ALL USING (
        EXISTS (
            SELECT 1 FROM public.conversaciones_ia c
            WHERE c.id_conversacion = mensajes_ia.id_conversacion
              AND c.id_cliente = get_id_cliente()
        )
    );

COMMIT;

-- =============================================================================
-- VERIFICACION (correr despues de aplicar):
--   SELECT relname, relrowsecurity FROM pg_class
--   WHERE relnamespace = 'public'::regnamespace AND relkind='r'
--   ORDER BY relname;
-- Esperado: todas en true.
-- =============================================================================

-- =============================================================================
-- ROLLBACK (si algo se rompe, correr este bloque):
-- BEGIN;
-- ALTER TABLE public.productos_fuente    DISABLE ROW LEVEL SECURITY;
-- ALTER TABLE public.capturas_precio     DISABLE ROW LEVEL SECURITY;
-- ALTER TABLE public.fuentes             DISABLE ROW LEVEL SECURITY;
-- ALTER TABLE public.planes              DISABLE ROW LEVEL SECURITY;
-- ALTER TABLE public.eventos_precio      DISABLE ROW LEVEL SECURITY;
-- ALTER TABLE public.auditoria_capturas  DISABLE ROW LEVEL SECURITY;
-- ALTER TABLE public.conversaciones_ia   DISABLE ROW LEVEL SECURITY;
-- ALTER TABLE public.reportes_generados  DISABLE ROW LEVEL SECURITY;
-- ALTER TABLE public.mensajes_ia         DISABLE ROW LEVEL SECURITY;
-- COMMIT;
-- =============================================================================
