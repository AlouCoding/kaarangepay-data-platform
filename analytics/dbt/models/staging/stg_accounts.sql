-- One row per wallet: business columns only, renamed for the marts.
select
    id            as account_id,
    account_type,
    status        as account_status,
    balance       as current_balance_xof,
    cast(created_at as timestamp) as created_at
from {{ source('raw', 'accounts') }}
