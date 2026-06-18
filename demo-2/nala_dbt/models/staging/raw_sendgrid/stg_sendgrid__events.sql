-- SendGrid webhook events, cleaned to one row per event.
-- Converts the epoch-SECOND timestamp to timestamptz and normalizes email.
with source as (

    select * from {{ source('raw_sendgrid', 'events') }}

)

select
    event_id,
    sg_message_id,
    lower(trim(email))                          as email,
    event                                       as event_type,
    to_timestamp(timestamp)                     as occurred_at,
    smtp_id,
    category,
    url,
    useragent,
    ip,
    reason,
    bounce_type,
    response,
    customer_id
from source
