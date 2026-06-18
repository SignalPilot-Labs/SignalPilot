with source as (
    select * from {{ source('raw_rafiki', 'merchants') }}
)

select
    merchant_id,
    legal_name,
    display_name,
    website,
    country                                   as hq_country,
    default_settlement_currency               as settlement_currency,
    -- legacy CSV string -> array
    string_to_array(accepts_stablecoins, ',') as accepted_stablecoins,
    industry,
    tier,
    -- standardize status: legacy 'PENDING_KYB' -> 'pending_kyb'
    case lower(status)
        when 'pending_kyb' then 'pending_kyb'
        else lower(status)
    end                                       as status,
    mrr_usd,
    account_manager,
    is_test,
    is_deleted,
    deleted_at,
    metadata,
    created_at                                as created_at,
    -- legacy 'updated' is an ISO string with no tz
    updated::timestamp                        as updated_at
from source
