-- stg_app_store__google_play_reviews: cleaned Play Store reviews, 1:1 with source.
-- Column shape aligned with stg_app_store__apple_reviews for a clean union downstream.
with source as (
    select * from {{ source('raw_app_store', 'google_play_reviews') }}
)

select
    review_id,
    'google_play'                              as store,
    null::text                                 as country_code,
    star_rating,
    review_title,
    review_text,
    author_name,
    app_version_name                           as app_version,
    false                                      as is_edited,
    submitted_at,
    developer_reply_text,
    developer_reply_at,
    (developer_reply_text is not null)         as has_developer_reply
from source
