-- Inteligencia comercial: match preciso de candidatos a competidor
-- =========================================================================
-- intel_perfil(nombre): parsea el nombre del producto y devuelve
--   - mag   : tamaño normalizado (ml o g; litros/kg -> x1000)
--   - clase : 'vol' (líquido/gel/suavizante) o 'mass' (polvo)
--   - conc  : true si es concentrado / diluible / para diluir
-- Nota Postgres: el límite de palabra es \y (NO \b, que es backspace).
--
-- intel_candidatos_por_producto(id_cliente): por cada producto propio, SKUs de
-- la competencia en la MISMA subcategoria canonica, MISMA clase (líquido/polvo),
-- MISMO tipo (concentrado/regular), TAMAÑO dentro de 0.66x-1.5x y precio entre
-- -15% y +25%. Excluye propios y ya mapeados. Ordena por cercania de precio.
-- security definer (bypass RLS) y parametrizado por id_cliente.

create or replace function intel_perfil(p_nombre text)
returns table(mag numeric, clase text, conc boolean)
language sql immutable as $$
  with n as (select lower(coalesce(p_nombre,'')) s),
  toks as (
    select replace(m[1],',','.')::numeric *
             case when m[2] in ('l','lt','lts','litro','litros','kg','kgs') then 1000 else 1 end as mag_ml,
           case when m[2] in ('kg','kgs','g','gr','grs','grm') then 'mass' else 'vol' end as clase_u
    from n, regexp_matches(n.s, '(\d+(?:[.,]\d+)?)\s*(litros|litro|lts|lt|ml|cc|cm3|kgs|kg|grs|grm|gr|g|l)\y', 'g') m
  ),
  best as (select mag_ml, clase_u from toks order by mag_ml desc limit 1)
  select
    (select mag_ml from best),
    case
      when (select s from n) ~ 'polvo' then 'mass'
      when (select s from n) ~ 'l[ií]quid|gel|suavizante|diluible|diluir|jab[oó]n l' then 'vol'
      else coalesce((select clase_u from best), 'vol')
    end,
    ((select s from n) ~ 'concentrad|diluible|diluir')
$$;

-- La definicion de intel_candidatos_por_producto(integer) se aplico via MCP.
-- Filtros clave (matches CTE):
--   pr.clase = mp.mi_clase
--   pr.conc  = mp.mi_conc
--   (pr.mag is null or mp.mi_mag is null or pr.mag between mp.mi_mag*0.66 and mp.mi_mag*1.5)
--   pp.precio between mp.mi_precio*0.85 and mp.mi_precio*1.25
