-- Fact table: one row per transaction attempt (completed or failed), at event-time grain.
with alerted as (
    select transfer_id as transaction_id from {{ ref('stg_fraud_alerts') }}
    union
    select cashout_id from {{ ref('stg_fraud_alerts') }}
)
select
    t.transaction_id,
    cast(strftime(t.occurred_at, '%Y%m%d') as integer)       as date_key,
    t.occurred_at,
    hour(t.occurred_at)                                      as hour_of_day,
    t.transaction_type,
    t.status,
    t.status = 'COMPLETED'                                   as is_completed,
    t.failure_reason,
    t.source_account_id,
    t.destination_account_id,
    t.amount_xof,
    t.fee_xof,
    case when t.status = 'COMPLETED' then t.amount_xof else 0 end   as completed_amount_xof,
    case when t.status = 'COMPLETED' then t.fee_xof else 0 end      as earned_fee_xof,
    date_diff('millisecond', t.occurred_at, t.recorded_at)          as ingestion_lag_ms,
    a.transaction_id is not null                             as is_flagged_fraud
from {{ ref('stg_transactions') }} t
left join alerted a using (transaction_id)
