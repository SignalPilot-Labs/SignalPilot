-- INTERPRETATION: List each musical style with counts of how many times it appears
-- as 1st preference, 2nd preference, and 3rd preference, one row per style
-- EXPECTED: one row per musical style (25 rows)

SELECT
    ms.StyleID,
    ms.StyleName,
    SUM(CASE WHEN mp.PreferenceSeq = 1 THEN 1 ELSE 0 END) AS first_preference_count,
    SUM(CASE WHEN mp.PreferenceSeq = 2 THEN 1 ELSE 0 END) AS second_preference_count,
    SUM(CASE WHEN mp.PreferenceSeq = 3 THEN 1 ELSE 0 END) AS third_preference_count
FROM Musical_Styles ms
LEFT JOIN Musical_Preferences mp ON ms.StyleID = mp.StyleID
GROUP BY ms.StyleID, ms.StyleName
ORDER BY ms.StyleID
