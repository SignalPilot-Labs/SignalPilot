-- EXPECTED: one row per musical style ranked by at least one user (~20 rows)
-- INTERPRETATION: For each musical style, compute weighted score (3×first + 2×second + 1×third
-- choice rankings), then compute absolute difference from the average weighted score across all
-- ranked styles.

WITH weighted_scores AS (
    SELECT
        ms.StyleID,
        ms.StyleName,
        SUM(CASE
            WHEN mp.PreferenceSeq = 1 THEN 3
            WHEN mp.PreferenceSeq = 2 THEN 2
            WHEN mp.PreferenceSeq = 3 THEN 1
            ELSE 0
        END) AS weighted_score
    FROM Musical_Styles ms
    JOIN Musical_Preferences mp ON ms.StyleID = mp.StyleID
    GROUP BY ms.StyleID, ms.StyleName
)
SELECT
    StyleID,
    StyleName,
    weighted_score,
    AVG(CAST(weighted_score AS REAL)) OVER () AS avg_weighted_score,
    ABS(weighted_score - AVG(CAST(weighted_score AS REAL)) OVER ()) AS abs_diff
FROM weighted_scores
ORDER BY StyleID
