-- EXPECTED: 2 rows (one for helmet used, one for helmet not used)
-- INTERPRETATION: Using parties table to classify motorcycle collisions by helmet usage,
-- computing fatality_rate = SUM(party_number_killed) / COUNT(DISTINCT case_id) per group.
-- Helmet usage determined from party_safety_equipment_1 and party_safety_equipment_2 fields.

WITH helmet_cases AS (
    SELECT
        case_id,
        SUM(party_number_killed) AS moto_fatalities,
        MAX(CASE WHEN party_safety_equipment_1 IN ('driver, motorcycle helmet used', 'passenger, motorcycle helmet used')
                      OR party_safety_equipment_2 IN ('driver, motorcycle helmet used', 'passenger, motorcycle helmet used')
                 THEN 1 ELSE 0 END) AS has_helmet_used,
        MAX(CASE WHEN party_safety_equipment_1 IN ('driver, motorcycle helmet not used', 'passenger, motorcycle helmet not used')
                      OR party_safety_equipment_2 IN ('driver, motorcycle helmet not used', 'passenger, motorcycle helmet not used')
                 THEN 1 ELSE 0 END) AS has_helmet_not_used
    FROM parties
    WHERE party_safety_equipment_1 LIKE '%motorcycle helmet%'
       OR party_safety_equipment_2 LIKE '%motorcycle helmet%'
    GROUP BY case_id
)
SELECT
    'helmet used' AS helmet_usage,
    CAST(SUM(moto_fatalities) AS REAL) / COUNT(*) AS fatality_rate
FROM helmet_cases
WHERE has_helmet_used = 1

UNION ALL

SELECT
    'helmet not used' AS helmet_usage,
    CAST(SUM(moto_fatalities) AS REAL) / COUNT(*) AS fatality_rate
FROM helmet_cases
WHERE has_helmet_not_used = 1
