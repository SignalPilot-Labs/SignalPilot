-- Support contact fact: one row per ticket / conversation across Zendesk and Intercom.
select
    source_system || ':' || contact_id          as support_contact_key,
    source_system,
    contact_id,
    customer_email,
    customer_code,
    subject,
    status,
    priority,
    channel,
    ticket_type,
    transfer_id,
    is_resolved,
    is_sla_breached,
    csat_score,
    is_satisfied,
    created_at,
    updated_at
from {{ ref('int_support_tickets') }}
