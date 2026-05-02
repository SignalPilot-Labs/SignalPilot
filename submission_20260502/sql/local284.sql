WITH stats AS (
    SELECT
        AVG("loss_rate_%") AS avg_loss_rate,
        SQRT(AVG("loss_rate_%" * "loss_rate_%") - AVG("loss_rate_%") * AVG("loss_rate_%")) AS stddev_loss_rate
    FROM veg_loss_rate_df
),
categorized AS (
    SELECT
        l."loss_rate_%",
        s.avg_loss_rate,
        s.stddev_loss_rate,
        CASE
            WHEN l."loss_rate_%" < (s.avg_loss_rate - s.stddev_loss_rate) THEN 'below'
            WHEN l."loss_rate_%" > (s.avg_loss_rate + s.stddev_loss_rate) THEN 'above'
            ELSE 'within'
        END AS category
    FROM veg_loss_rate_df l
    CROSS JOIN stats s
)
SELECT
    avg_loss_rate,
    SUM(CASE WHEN category = 'below' THEN 1 ELSE 0 END) AS below_avg_stddev_count,
    SUM(CASE WHEN category = 'within' THEN 1 ELSE 0 END) AS within_avg_stddev_count,
    SUM(CASE WHEN category = 'above' THEN 1 ELSE 0 END) AS above_avg_stddev_count
FROM categorized
