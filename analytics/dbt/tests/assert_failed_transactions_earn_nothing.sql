-- Business rule: a failed transaction moves no money and earns no fee in the reporting layer.
select transaction_id
from {{ ref('fct_transactions') }}
where not is_completed and (completed_amount_xof <> 0 or earned_fee_xof <> 0)
