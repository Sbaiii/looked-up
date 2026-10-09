{{ config(materialized='table') }}
-- (lang, title) -> qid; one QID per title within a language (unique key of wb_items_per_site).
select lang, title, cast(qid as bigint) as qid
from {{ source('lake', 'sitelinks') }}
