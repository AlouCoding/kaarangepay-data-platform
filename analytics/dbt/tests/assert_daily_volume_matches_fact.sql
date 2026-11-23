-- Reconciliation between two marts: the daily aggregate must add up to the fact table.
select 'volume' as measure
from (select sum(volume_xof) as a from {{ ref('agg_daily_kpis') }}) d,
     (select sum(completed_amount_xof) as b from {{ ref('fct_transactions') }}) f
where d.a <> f.b
