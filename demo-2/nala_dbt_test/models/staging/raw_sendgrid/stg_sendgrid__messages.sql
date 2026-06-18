-- SendGrid email sends, cleaned to one row per message.
-- Normalizes the dirty recipient email and parses the ISO-Z send timestamp.
with source as (

    select * from {{ source('raw_sendgrid', 'messages') }}

)

select
    sg_message_id,
    to_email                                   as to_email_raw,
    lower(trim(to_email))                       as to_email,
    from_email,
    subject,
    template_id,
    category,
    asm_group_id,
    lower(msg_status)                           as message_status,
    opens_count,
    clicks_count,
    customer_id,
    ip_pool,
    is_marketing,
    sent_at::timestamptz                        as sent_at,
    raw_payload
from source
