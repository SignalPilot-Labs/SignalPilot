-- Per-customer messaging engagement across Braze (push/in-app), SendGrid (email),
-- and Twilio (SMS). Resolves every channel to the canonical customer_id:
--   Braze keys on customer_code -> mapped via stg_core_transfers__customers
--   SendGrid / Twilio key on the integer customer_id directly
-- Braze messages_sent is an event stream (event_type sent/open/click/...);
-- SendGrid messages carry opens_count/clicks_count per message; Twilio is send-only.
with customers as (

    select customer_id, customer_code
    from {{ ref('stg_core_transfers__customers') }}

),

braze_raw as (

    select
        c.customer_id,
        m.event_type
    from {{ ref('stg_braze__messages_sent') }} m
    inner join customers c
        on m.customer_code = c.customer_code
    where m.customer_code is not null

),

braze as (

    select
        customer_id,
        'braze'                                                    as channel,
        count(*) filter (where event_type = 'sent')                as sends,
        count(*) filter (where event_type = 'open')                as opens,
        count(*) filter (where event_type = 'click')               as clicks
    from braze_raw
    group by 1

),

sendgrid as (

    select
        customer_id,
        'sendgrid'                                                 as channel,
        count(*)                                                   as sends,
        sum(coalesce(opens_count, 0))                              as opens,
        sum(coalesce(clicks_count, 0))                             as clicks
    from {{ ref('stg_sendgrid__messages') }}
    where customer_id is not null
    group by 1

),

twilio as (

    select
        customer_id,
        'twilio'                                                   as channel,
        count(*)                                                   as sends,
        0                                                          as opens,
        0                                                          as clicks
    from {{ ref('stg_twilio__messages') }}
    where customer_id is not null
    group by 1

)

select * from braze
union all
select * from sendgrid
union all
select * from twilio
