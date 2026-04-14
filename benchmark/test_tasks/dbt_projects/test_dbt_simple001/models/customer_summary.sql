{{ config(materialized='table') }}

SELECT id, name, city
FROM {{ source('raw', 'raw_customers') }}
