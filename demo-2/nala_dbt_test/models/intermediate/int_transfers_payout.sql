-- int_transfers_payout: each transfer joined to its payout (receive) leg.
-- The internal canonical record is core_transfers.payout_attempts (one transfer
-- can have several attempts). We pick the best attempt (SUCCESS first, else the
-- latest) then enrich with the external partner reference from M-PESA / Flutterwave
-- (both carry nala_transfer_id = transfers.transfer_id).
-- Grain: one row per transfer_id.
with transfers as (
    select transfer_id, payout_partner, rail
    from {{ ref('stg_core_transfers__transfers') }}
),

attempts as (
    select
        transfer_id,
        attempt_id                                      as payout_attempt_id,
        attempt_no,
        partner                                         as payout_partner,
        rail                                            as payout_rail,
        partner_reference,
        msisdn,
        account_number,
        status                                          as payout_status,
        response_code,
        response_message,
        requested_at,
        completed_at                                    as payout_completed_at,
        row_number() over (
            partition by transfer_id
            order by case when status = 'SUCCESS' then 0 else 1 end,
                     attempt_no desc
        )                                               as rn
    from {{ ref('stg_core_transfers__payout_attempts') }}
),

mpesa as (
    select
        nala_transfer_id                                as transfer_id,
        mpesa_receipt                                   as external_reference,
        recipient_msisdn                                as external_msisdn,
        payout_status                                   as external_status,
        completed_at                                    as external_completed_at,
        row_number() over (
            partition by nala_transfer_id order by completed_at desc nulls last
        )                                               as rn
    from {{ ref('stg_mpesa__b2c_requests') }}
    where nala_transfer_id is not null
),

flutterwave as (
    select
        nala_transfer_id                                as transfer_id,
        reference                                       as external_reference,
        recipient_phone                                 as external_msisdn,
        transfer_status                                 as external_status,
        created_at                                      as external_completed_at,
        row_number() over (
            partition by nala_transfer_id order by created_at desc
        )                                               as rn
    from {{ ref('stg_flutterwave__transfers') }}
    where nala_transfer_id is not null
)

select
    t.transfer_id,
    a.payout_attempt_id,
    a.attempt_no,
    coalesce(a.payout_partner, t.payout_partner)        as payout_partner,
    coalesce(a.payout_rail, t.rail)                     as payout_rail,
    a.partner_reference,
    a.payout_status,
    a.response_code,
    a.response_message,
    a.requested_at,
    a.payout_completed_at,
    coalesce(a.msisdn, m.external_msisdn, fw.external_msisdn)       as payout_msisdn,
    a.account_number,

    -- external partner enrichment
    case
        when m.transfer_id is not null  then 'mpesa'
        when fw.transfer_id is not null then 'flutterwave'
        else null
    end                                                 as external_rail_source,
    coalesce(m.external_reference, fw.external_reference)          as external_reference,
    coalesce(m.external_status, fw.external_status)               as external_status,
    coalesce(m.external_completed_at, fw.external_completed_at)   as external_completed_at
from transfers t
left join attempts    a  on t.transfer_id = a.transfer_id  and a.rn = 1
left join mpesa       m  on t.transfer_id = m.transfer_id  and m.rn = 1
left join flutterwave fw on t.transfer_id = fw.transfer_id and fw.rn = 1
