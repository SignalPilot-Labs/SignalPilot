-- stg_app_store__apple_reviews: cleaned App Store reviews, 1:1 with source.
with source as (
    select * from {{ source('raw_app_store', 'apple_reviews') }}
)

select
    review_id,
    'apple'                                    as store,
    territory                                  as country_code,
    rating                                     as star_rating,
    title                                      as review_title,
    body                                       as review_text,
    reviewer_nickname                          as author_name,
    app_version,
    is_edited,
    review_date                                as submitted_at,
    developer_response                         as developer_reply_text,
    developer_response_date                    as developer_reply_at,
    (developer_response is not null)           as has_developer_reply
from source
