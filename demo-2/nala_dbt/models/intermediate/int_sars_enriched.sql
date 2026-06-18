-- Suspicious Activity Reports enriched with the linked transfer and customer.
-- transfer_id and customer_code on a SAR are sparse / dirty, so joins are LEFT.
with sars as (
    select * from {{ ref('stg_compliance__sars') }}
),

transfers as (
    select * from {{ ref('stg_core_transfers__transfers') }}
),

customers as (
    select * from {{ ref('stg_core_transfers__customers') }}
)

select
    s.sar_id,
    s.sar_ref,
    s.customer_code,
    s.customer_uuid,
    s.subject_name,
    s.transfer_id,
    s.activity_type,
    s.status,
    s.priority,
    s.regulator,
    s.filing_reference,
    s.amount_usd,
    s.filed_by,
    -- linked transfer attributes
    t.customer_id                               as transfer_customer_id,
    t.send_country,
    t.receive_country,
    t.send_currency,
    t.receive_currency,
    t.send_amount                               as transfer_send_amount,
    t.status                                    as transfer_status,
    t.payout_partner,
    -- linked customer attributes (resolved via customer_code)
    c.customer_id,
    c.kyc_tier,
    c.account_status,
    s.filed_at,
    s.created_at,
    s.updated_at
from sars s
left join transfers t
    on s.transfer_id = t.transfer_id
left join customers c
    on s.customer_code = c.customer_code
