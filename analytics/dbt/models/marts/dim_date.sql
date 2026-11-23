-- Calendar dimension covering every day with activity. Payday period and holidays follow the
-- assumptions of the traffic generator (patterns.py), so dashboards can explain the peaks.
with bounds as (
    select min(cast(occurred_at as date)) as first_day, max(cast(occurred_at as date)) as last_day
    from {{ ref('stg_transactions') }}
),
days as (
    select cast(d as date) as day
    from bounds, range(first_day, last_day + interval 1 day, interval 1 day) as t(d)
)
select
    cast(strftime(day, '%Y%m%d') as integer)                           as date_key,
    day,
    isodow(day)                                                         as iso_day_of_week,
    ['Lundi','Mardi','Mercredi','Jeudi','Vendredi','Samedi','Dimanche'][isodow(day)] as day_name_fr,
    isodow(day) >= 6                                                    as is_weekend,
    dayofmonth(day) >= 25 or dayofmonth(day) <= 3                   as is_payday_period,
    strftime(day, '%Y-%m')                                              as year_month
from days
