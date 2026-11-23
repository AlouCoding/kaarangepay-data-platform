-- Ledger invariant: the treasury mirrors all issued e-money, so all balances sum to zero.
select sum(current_balance_xof) as total
from {{ ref('dim_account') }}
having sum(current_balance_xof) <> 0
