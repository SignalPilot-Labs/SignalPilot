-- M-PESA async result callbacks. Daraja CamelCase -> snake_case.
-- Filter duplicate re-posts (is_duplicate) and convert epoch-ms receipt time.
with source as (
    select * from {{ source('raw_mpesa', 'callbacks') }}
)

select
    "callback_id"                                        as callback_id,
    "callback_type"                                      as callback_type,
    "ConversationID"                                     as conversation_id,
    "OriginatorConversationID"                           as originator_conversation_id,
    "CheckoutRequestID"                                  as checkout_request_id,
    "MerchantRequestID"                                  as merchant_request_id,
    "ResultType"                                         as result_type,
    "ResultCode"                                         as result_code,
    "ResultDesc"                                         as result_desc,
    "TransactionID"                                      as mpesa_receipt,
    case when "ResultCode" = 0 then 'success' else 'failed' end as result_status,
    to_timestamp("received_at_ms" / 1000.0)              as received_at,
    "ResultParameters"                                   as result_parameters,
    "raw_payload"                                        as raw_payload
from source
where not "is_duplicate"
