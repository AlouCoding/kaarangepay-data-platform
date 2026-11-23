select
    id              as entry_id,
    transaction_id,
    account_id,
    direction,
    amount          as amount_xof,
    signed_amount   as signed_amount_xof,      -- + credit / - debit
    balance_after   as balance_after_xof,
    cast(occurred_at as timestamp) as occurred_at
from {{ source('raw', 'ledger_entries') }}
