-- One row per day: what the business looks at every morning.
select
    d.date_key,
    d.day,
    d.day_name_fr,
    d.is_weekend,
    d.is_payday_period,
    count(f.transaction_id)                                          as transactions,
    count(f.transaction_id) filter (where f.is_completed)            as completed,
    round(1 - count(f.transaction_id) filter (where f.is_completed)
              / nullif(count(f.transaction_id), 0), 4)               as failure_rate,
    coalesce(sum(f.completed_amount_xof), 0)                         as volume_xof,
    coalesce(sum(f.earned_fee_xof), 0)                               as fees_xof,
    count(distinct f.source_account_id) filter (where f.is_completed) as active_payers,
    count(f.transaction_id) filter (where f.is_flagged_fraud)        as flagged_fraud_tx
from {{ ref('dim_date') }} d
left join {{ ref('fct_transactions') }} f using (date_key)
group by all
