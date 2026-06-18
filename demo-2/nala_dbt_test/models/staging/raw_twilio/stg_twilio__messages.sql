-- Twilio SMS messages, cleaned to one row per message.
-- Parses RFC2822 timestamp strings into timestamptz and casts the signed
-- string price into a numeric USD cost.
with source as (

    select * from {{ source('raw_twilio', 'messages') }}

)

select
    message_sid,
    account_sid,
    messaging_service_sid,
    to_number                                              as to_number_raw,
    -- normalized E.164: strip spaces, convert 00-prefix to +, ensure leading +
    case
        when to_number is null then null
        else
            case
                when left(regexp_replace(trim(to_number), '\s', '', 'g'), 2) = '00'
                    then '+' || substr(regexp_replace(trim(to_number), '\s', '', 'g'), 3)
                when left(regexp_replace(trim(to_number), '\s', '', 'g'), 1) = '+'
                    then regexp_replace(trim(to_number), '\s', '', 'g')
                else '+' || regexp_replace(trim(to_number), '\s', '', 'g')
            end
    end                                                    as to_number,
    from_number,
    body,
    num_segments,
    num_media,
    direction,
    message_type,
    lower(status)                                          as status,
    error_code,
    error_message,
    nullif(price, '')::numeric(18, 6)                      as price_usd,
    price_unit,
    customer_id,
    to_timestamp(date_created, 'Dy, DD Mon YYYY HH24:MI:SS')  as created_at,
    to_timestamp(date_sent,    'Dy, DD Mon YYYY HH24:MI:SS')  as sent_at,
    to_timestamp(date_updated, 'Dy, DD Mon YYYY HH24:MI:SS')  as updated_at,
    api_version,
    raw_payload
from source
