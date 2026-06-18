-- Unions Apple App Store + Google Play reviews into one common grain.
-- Both staging models already share an aligned column shape.
with apple as (

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
        developer_reply_text,
        developer_reply_at,
        has_developer_reply
    from {{ ref('stg_app_store__apple_reviews') }}

),

google_play as (

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
        developer_reply_text,
        developer_reply_at,
        has_developer_reply
    from {{ ref('stg_app_store__google_play_reviews') }}

)

select * from apple
union all
select * from google_play
