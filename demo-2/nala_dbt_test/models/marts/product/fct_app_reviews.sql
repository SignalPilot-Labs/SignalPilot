-- App store reviews fact, one row per review (Apple + Google Play unioned).
-- review_id is a UUID unique across both stores.
with reviews as (

    select * from {{ ref('int_reviews_unioned') }}

)

select
    review_id,
    store,
    country_code,
    star_rating,
    review_title,
    review_text,
    author_name,
    app_version,
    is_edited,
    submitted_at,
    cast(submitted_at as date)             as submitted_date,
    has_developer_reply,
    developer_reply_at,
    (star_rating >= 4)                     as is_positive,
    (star_rating <= 2)                     as is_negative
from reviews
