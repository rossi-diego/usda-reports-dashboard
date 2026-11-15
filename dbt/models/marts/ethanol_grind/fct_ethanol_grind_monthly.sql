-- U.S. corn-for-ethanol grind per month (NASS Grain Crushings and Co-Products Production),
-- latest revised value of every metric. Marketing year September-August (the corn year used
-- by WASDE), so month_of_my 1 = September. Corn in thousand bushels (k_bu); co-products in
-- short tons as printed by NASS.
--   first_release_*  the release that first printed the month (point-in-time availability);
--   latest_release_* the release whose (revised) value is shown.
with v as (
    select * from {{ ref('stg_ethanol_grind') }}
    where value is not null
),

ranked as (
    select
        *,
        row_number() over (partition by month, metric order by release_ts_utc desc) as rn_latest,
        row_number() over (partition by month, metric order by release_ts_utc)      as rn_first,
        count(*) over (partition by month, metric)                                  as n_vintages
    from v
),

bu as (
    select bu_per_unit from {{ ref('dim_unit') }}
    where unit_id = 'k_bu' and commodity_id = 'corn'
),

wide as (
    select
        month,
        any_value(market_year)                                                        as market_year,
        any_value(my_start)                                                           as my_start,
        any_value(month_of_my)                                                        as month_of_my,
        max(value) filter (where metric = 'corn_fuel_alcohol_kbu' and rn_latest = 1)   as corn_fuel_alcohol_kbu,
        max(value) filter (where metric = 'corn_fuel_dry_mill_kbu' and rn_latest = 1)  as corn_fuel_dry_mill_kbu,
        max(value) filter (where metric = 'corn_fuel_wet_mill_kbu' and rn_latest = 1)  as corn_fuel_wet_mill_kbu,
        max(value) filter (where metric = 'corn_beverage_alcohol_kbu' and rn_latest = 1) as corn_beverage_alcohol_kbu,
        max(value) filter (where metric = 'corn_industrial_alcohol_kbu' and rn_latest = 1) as corn_industrial_alcohol_kbu,
        max(value) filter (where metric = 'corn_wet_mill_other_kbu' and rn_latest = 1)  as corn_wet_mill_other_kbu,
        max(value) filter (where metric = 'ddg_st' and rn_latest = 1)                  as ddg_st,
        max(value) filter (where metric = 'ddgs_st' and rn_latest = 1)                 as ddgs_st,
        max(value) filter (where metric = 'cds_syrup_st' and rn_latest = 1)            as cds_syrup_st,
        max(value) filter (where metric = 'corn_oil_st' and rn_latest = 1)             as corn_oil_st,
        max(value) filter (where metric = 'dwg_st' and rn_latest = 1)                  as dwg_st,
        max(value) filter (where metric = 'modified_dwg_st' and rn_latest = 1)         as modified_dwg_st,
        max(value) filter (where metric = 'corn_germ_meal_st' and rn_latest = 1)       as corn_germ_meal_st,
        max(value) filter (where metric = 'corn_gluten_feed_st' and rn_latest = 1)     as corn_gluten_feed_st,
        max(value) filter (where metric = 'corn_gluten_meal_st' and rn_latest = 1)     as corn_gluten_meal_st,
        max(value) filter (where metric = 'wet_corn_gluten_feed_st' and rn_latest = 1) as wet_corn_gluten_feed_st,
        max(value) filter (where metric = 'co2_captured_st' and rn_latest = 1)         as co2_captured_st,
        max(value) filter (where metric = 'corn_fuel_alcohol_kbu' and rn_first = 1)    as corn_fuel_alcohol_kbu_first,
        max(release_key) filter (where metric = 'corn_fuel_alcohol_kbu' and rn_first = 1) as first_release_key,
        max(release_ts_utc) filter (where metric = 'corn_fuel_alcohol_kbu' and rn_first = 1) as first_release_ts_utc,
        max(column_role) filter (where metric = 'corn_fuel_alcohol_kbu' and rn_first = 1) as first_printed_as,
        max(release_key) filter (where metric = 'corn_fuel_alcohol_kbu' and rn_latest = 1) as latest_release_key,
        max(release_ts_utc) filter (where metric = 'corn_fuel_alcohol_kbu' and rn_latest = 1) as latest_release_ts_utc,
        max(source_url) filter (where metric = 'corn_fuel_alcohol_kbu' and rn_latest = 1) as source_url,
        cast(max(n_vintages) filter (where metric = 'corn_fuel_alcohol_kbu') as integer) as n_vintages
    from ranked
    group by month
)

select
    w.market_year,
    w.my_start,
    w.month_of_my,
    w.month,
    w.corn_fuel_alcohol_kbu,
    w.corn_fuel_alcohol_kbu * b.bu_per_unit                              as corn_fuel_alcohol_bu,
    w.corn_fuel_dry_mill_kbu,
    w.corn_fuel_wet_mill_kbu,
    w.corn_beverage_alcohol_kbu,
    w.corn_industrial_alcohol_kbu,
    w.corn_wet_mill_other_kbu,
    w.ddg_st,
    w.ddgs_st,
    w.cds_syrup_st,
    w.corn_oil_st,
    w.dwg_st,
    w.modified_dwg_st,
    w.corn_germ_meal_st,
    w.corn_gluten_feed_st,
    w.corn_gluten_meal_st,
    w.wet_corn_gluten_feed_st,
    w.co2_captured_st,
    -- short tons of DDGS per thousand bushels ground (a corn-ethanol co-product yield, the
    -- analogue of oilseed crush's oil yield).
    w.ddgs_st / nullif(w.corn_fuel_alcohol_kbu, 0)                       as ddgs_yield_st_per_kbu,
    w.corn_fuel_alcohol_kbu_first,
    w.corn_fuel_alcohol_kbu <> w.corn_fuel_alcohol_kbu_first             as is_revised,
    w.first_release_key,
    w.first_release_ts_utc,
    w.first_printed_as,
    w.latest_release_key,
    w.latest_release_ts_utc,
    w.n_vintages,
    w.source_url,
    w.month = max(w.month) over ()                                      as is_latest_month
from wide as w
cross join bu as b
where w.corn_fuel_alcohol_kbu is not null
