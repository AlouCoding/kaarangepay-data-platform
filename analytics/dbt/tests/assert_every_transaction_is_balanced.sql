-- Ledger invariant, re-checked in the warehouse: debits = credits for every transaction.
-- A dbt singular test fails when this query returns rows.
select transaction_id, sum(signed_amount_xof) as net
from {{ ref('stg_ledger_entries') }}
group by transaction_id
having sum(signed_amount_xof) <> 0
