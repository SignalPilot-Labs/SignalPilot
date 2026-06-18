-- Unified support contacts across Zendesk tickets and Intercom conversations,
-- brought to a common grain: one row per support contact. CSAT from the Zendesk
-- satisfaction ratings is attached to the originating ticket.
with zendesk_tickets as (
    select * from {{ ref('stg_zendesk__tickets') }}
),

zendesk_csat as (
    select
        ticket_id,
        score,
        is_satisfied,
        -- a ticket can have multiple ratings; keep the most recent
        row_number() over (
            partition by ticket_id order by created_at desc, satisfaction_rating_id desc
        ) as rn
    from {{ ref('stg_zendesk__satisfaction_ratings') }}
),

zendesk_csat_latest as (
    select ticket_id, score, is_satisfied
    from zendesk_csat
    where rn = 1
),

intercom as (
    select * from {{ ref('stg_intercom__conversations') }}
),

zendesk_unified as (
    select
        'zendesk'                               as source_system,
        t.ticket_id::text                       as contact_id,
        t.requester_email                       as customer_email,
        cast(null as text)                      as customer_code,
        t.subject,
        t.status,
        t.priority,
        t.channel,
        t.ticket_type,
        t.transfer_id,
        t.is_resolved,
        cast(null as boolean)                   as is_sla_breached,
        coalesce(t.satisfaction, csat.score)    as csat_score,
        csat.is_satisfied,
        t.created_at,
        t.updated_at
    from zendesk_tickets t
    left join zendesk_csat_latest csat
        on t.ticket_id = csat.ticket_id
),

intercom_unified as (
    select
        'intercom'                              as source_system,
        i.conversation_id::text                 as contact_id,
        i.contact_email                         as customer_email,
        i.customer_code,
        i.source_subject                        as subject,
        i.state                                 as status,
        i.priority,
        i.source_type                           as channel,
        cast(null as text)                      as ticket_type,
        cast(null as text)                      as transfer_id,
        case when i.state = 'closed' then true else false end as is_resolved,
        i.is_sla_breached,
        case
            when i.csat_rating is null then null
            when i.csat_rating >= 4 then 'good'
            else 'bad'
        end                                     as csat_score,
        case
            when i.csat_rating is null then null
            when i.csat_rating >= 4 then 1
            else 0
        end                                     as is_satisfied,
        i.created_at,
        i.updated_at
    from intercom i
)

select * from zendesk_unified
union all
select * from intercom_unified
