select
    transaction_type,
    count(*)                                                as transactions,
    count(*) filter (where is_completed)                    as completed,
    round(1 - count(*) filter (where is_completed) / count(*), 4) as failure_rate,
    sum(completed_amount_xof)                               as volume_xof,
    sum(earned_fee_xof)                                     as fees_xof,
    round(avg(amount_xof) filter (where is_completed))      as avg_amount_xof
from {{ ref('fct_transactions') }}
group by all
