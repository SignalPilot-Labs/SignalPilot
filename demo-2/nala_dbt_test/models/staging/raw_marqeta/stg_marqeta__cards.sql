-- One row per Marqeta-issued card. ISO-offset strings -> timestamptz.
with source as (
    select * from {{ source('raw_marqeta', 'cards') }}
)

select
    token                                               as card_id,
    user_token                                          as cardholder_id,
    card_product_token                                  as card_product_id,

    last_four,
    pan_token,
    expiration                                          as expiration_mmyy,
    pin_is_set                                          as is_pin_set,

    -- standardize state to lowercase
    lower(state)                                        as status,
    state_reason,
    fulfillment_status,
    instrument_type,

    -- ISO-8601 offset strings -> timestamptz
    created_time::timestamptz                           as created_at,
    expiration_time::timestamptz                        as expires_at
from source
