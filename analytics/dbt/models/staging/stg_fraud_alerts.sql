select
    alert_id,
    rule,
    account_id         as mule_account_id,
    sender_account_id  as victim_account_id,
    transfer_id,
    transfer_amount    as transfer_amount_xof,
    cast(transfer_at as timestamp) as transfer_at,
    cashout_id,
    cashout_amount     as cashout_amount_xof,
    cast(cashout_at as timestamp) as cashout_at,
    minutes_between,
    cast(detected_at as timestamp) as detected_at
from {{ source('raw', 'fraud_alerts') }}
-- the Kafka sink is at-least-once and the Delta sink exactly-once; dedupe anyway, on the deterministic id
qualify row_number() over (partition by alert_id order by detected_at) = 1
