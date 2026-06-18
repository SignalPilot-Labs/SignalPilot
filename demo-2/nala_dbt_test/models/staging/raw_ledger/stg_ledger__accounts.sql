-- Chart of accounts, 1:1 with source. Standardizes flags and exposes the
-- customer_code join key (trimmed) for customer wallet accounts.
with source as (
    select * from {{ source('raw_ledger', 'accounts') }}
)

select
    account_id,
    account_code,
    account_name,
    account_type_id,
    upper(currency)                               as currency,
    parent_account_id,
    nullif(trim(customer_code), '')               as customer_code,
    coalesce(is_contra, false)                    as is_contra,
    coalesce(is_active, true)                     as is_active,
    coalesce(is_deleted, false)                   as is_deleted,
    deleted_at,
    created_at                                    as created_at,
    updated_at,
    metadata
from source
