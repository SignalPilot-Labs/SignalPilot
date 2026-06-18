-- Payout rail attempts per transfer, 1:1 with raw_core_transfers.payout_attempts.
-- requested_at arrives as an ISO-Z text string; cast it into a clean timestamptz.
with source as (
    select * from {{ source('raw_core_transfers', 'payout_attempts') }}
)

select
    attempt_id,
    transfer_id,
    attempt_no,
    partner,
    rail,
    partner_reference,
    msisdn,
    account_number,
    upper(status)                       as status,
    response_code,
    response_message,
    -- requested_at is ISO-8601 'Z' text -> timestamptz
    requested_at::timestamptz           as requested_at,
    completed_at,
    raw_response
from source
