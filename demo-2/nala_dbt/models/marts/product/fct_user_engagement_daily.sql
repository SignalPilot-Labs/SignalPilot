-- Daily user-engagement fact, one row per activity_date. Combines product DAU
-- with that day's outbound messaging volume (Braze + SendGrid + Twilio sends).
-- DAU and messaging are independent daily aggregates joined on date via a spine
-- so a day with messaging but no events (or vice versa) still appears.
with dau as (

    select activity_date, active_users
    from {{ ref('int_active_users_daily') }}

),

braze_daily as (

    select
        cast(sent_at as date)              as activity_date,
        count(*) filter (where event_type = 'sent')  as braze_sends
    from {{ ref('stg_braze__messages_sent') }}
    where sent_at is not null
    group by 1

),

sendgrid_daily as (

    select
        cast(sent_at as date)              as activity_date,
        count(*)                           as sendgrid_sends,
        sum(coalesce(opens_count, 0))      as sendgrid_opens,
        sum(coalesce(clicks_count, 0))     as sendgrid_clicks
    from {{ ref('stg_sendgrid__messages') }}
    where sent_at is not null
    group by 1

),

twilio_daily as (

    select
        cast(sent_at as date)              as activity_date,
        count(*)                           as twilio_sends
    from {{ ref('stg_twilio__messages') }}
    where sent_at is not null
    group by 1

),

spine as (

    select activity_date from dau
    union
    select activity_date from braze_daily
    union
    select activity_date from sendgrid_daily
    union
    select activity_date from twilio_daily

)

select
    s.activity_date,
    coalesce(d.active_users, 0)            as active_users,
    coalesce(b.braze_sends, 0)             as braze_sends,
    coalesce(sg.sendgrid_sends, 0)         as sendgrid_sends,
    coalesce(sg.sendgrid_opens, 0)         as sendgrid_opens,
    coalesce(sg.sendgrid_clicks, 0)        as sendgrid_clicks,
    coalesce(tw.twilio_sends, 0)           as twilio_sends,
    coalesce(b.braze_sends, 0)
        + coalesce(sg.sendgrid_sends, 0)
        + coalesce(tw.twilio_sends, 0)     as total_messages_sent
from spine s
left join dau d             on s.activity_date = d.activity_date
left join braze_daily b     on s.activity_date = b.activity_date
left join sendgrid_daily sg on s.activity_date = sg.activity_date
left join twilio_daily tw   on s.activity_date = tw.activity_date
