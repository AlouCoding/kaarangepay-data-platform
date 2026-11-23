select
    id                     as transaction_id,
    transaction_type,
    status,
    source_account_id,
    destination_account_id,
    amount                 as amount_xof,
    fee                    as fee_xof,
    failure_reason,
    cast(occurred_at as timestamp) as occurred_at,                                -- event time: when the customer acted
    cast(recorded_at as timestamp) as recorded_at                                 -- processing time: when payment-core stored it
from {{ source('raw', 'transactions') }}
