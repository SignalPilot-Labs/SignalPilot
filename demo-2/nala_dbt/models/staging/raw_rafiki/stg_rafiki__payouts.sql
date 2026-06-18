with source as (
    select * from {{ source('raw_rafiki', 'payouts') }}
)

select
    payout_id,
    merchant_id,
    idempotency_key,
    recipient_name,             -- PII
    recipient_account,          -- PII: MSISDN / bank acct / IBAN
    recipient_type,
    rail,
    destination_country,
    currency                    as local_currency,
    amount_local,
    amount_usd,
    fx_rate,
    fee_usd,
    fx_lock_id,
    -- standardize status: legacy 'PENDING_OLD' -> 'processing'
    case
        when lower(status) in ('processing', 'pending_old') then 'processing'
        else lower(status)
    end                         as status,
    failure_reason,
    partner,
    settlement_id,
    canonical_cid,              -- cross-source: app customer id when set
    -- created is epoch milliseconds
    to_timestamp(created / 1000.0) as created_at,
    -- completed_at is an ISO string with no tz
    completed_at::timestamp        as completed_at,
    metadata
from source
