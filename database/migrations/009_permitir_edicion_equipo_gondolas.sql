-- El equipo de un mismo cliente puede corregir registros de góndolas,
-- independientemente de quién haya cargado la evidencia originalmente.

BEGIN;

DROP POLICY IF EXISTS gondolas_perfectas_solo_su_cliente ON public.gondolas_perfectas;
CREATE POLICY gondolas_perfectas_solo_su_cliente ON public.gondolas_perfectas
    FOR ALL
    USING (id_cliente = get_id_cliente())
    WITH CHECK (id_cliente = get_id_cliente());

COMMIT;
