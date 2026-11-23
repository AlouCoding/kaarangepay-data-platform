select
    alert_id,
    rule,
    victim_account_id,
    mule_account_id,
    transfer_id,
    transfer_amount_xof,
    transfer_at,
    cashout_id,
    cashout_amount_xof,
    cashout_at,
    round(minutes_between, 1)                                   as minutes_between,
    round(cashout_amount_xof / transfer_amount_xof, 4)          as cashout_ratio,
    cast(strftime(cashout_at, '%Y%m%d') as integer)             as date_key,
    detected_at
from {{ ref('stg_fraud_alerts') }}
