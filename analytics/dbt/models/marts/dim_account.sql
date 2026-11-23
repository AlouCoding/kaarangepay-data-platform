with flagged as (
    select mule_account_id as account_id, count(*) as fraud_alerts_as_mule
    from {{ ref('stg_fraud_alerts') }}
    group by 1
)
select
    a.account_id,
    a.account_type,
    a.account_status,
    a.current_balance_xof,
    cast(a.created_at as date)                       as opened_on,
    a.account_type = 'SYSTEM'                        as is_system_account,
    coalesce(f.fraud_alerts_as_mule, 0)              as fraud_alerts_as_mule
from {{ ref('stg_accounts') }} a
left join flagged f using (account_id)
