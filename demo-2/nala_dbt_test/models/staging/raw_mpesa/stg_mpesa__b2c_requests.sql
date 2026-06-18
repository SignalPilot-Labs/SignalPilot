-- M-PESA B2C payout requests. Daraja CamelCase -> snake_case.
-- Standardize the messy status: ResultCode is NULL until the callback lands,
-- so derive a clean status enum (success / failed / pending).
with source as (
    select * from {{ source('raw_mpesa', 'b2c_requests') }}
)

select
    "OriginatorConversationID"                           as originator_conversation_id,
    "ConversationID"                                     as conversation_id,
    "TransactionID"                                      as mpesa_receipt,
    "InitiatorName"                                      as initiator_name,
    "CommandID"                                          as command_id,
    "Amount"                                             as amount,
    coalesce("currency", 'KES')                          as currency,
    "PartyA"                                             as party_a_short_code,
    "PartyB"                                             as recipient_msisdn,       -- PII
    "Remarks"                                            as remarks,
    "Occasion"                                           as occasion,
    "ResponseCode"                                       as response_code,
    "ResponseDescription"                                as response_description,
    "ResultCode"                                         as result_code,
    "ResultDesc"                                         as result_desc,
    "ReceiverPartyPublicName"                            as receiver_party_public_name,  -- PII (masked)
    "B2CRecipientIsRegisteredCustomer"                   as recipient_is_registered,
    "B2CWorkingAccountAvailableFunds"                    as working_account_funds,
    "B2CUtilityAccountAvailableFunds"                    as utility_account_funds,
    "nala_transfer_id"                                   as nala_transfer_id,
    "nala_customer_code"                                 as nala_customer_code,
    case
        when "ResultCode" = 0 then 'success'
        when "ResultCode" is null then 'pending'
        else 'failed'
    end                                                  as payout_status,
    -- TransactionCompletedDateTime is dd.MM.yyyy HH:mm:ss (success only)
    to_timestamp("TransactionCompletedDateTime", 'DD.MM.YYYY HH24:MI:SS') as completed_at,
    "created"                                            as ingested_at,
    "raw_payload"                                        as raw_payload
from source
