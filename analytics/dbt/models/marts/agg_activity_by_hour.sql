-- Heatmap source: when do people transact? (day of week x hour, completed transactions)
select
    d.iso_day_of_week,
    d.day_name_fr,
    f.hour_of_day,
    count(*)                    as transactions,
    sum(f.completed_amount_xof) as volume_xof
from {{ ref('fct_transactions') }} f
join {{ ref('dim_date') }} d using (date_key)
where f.is_completed
group by all
