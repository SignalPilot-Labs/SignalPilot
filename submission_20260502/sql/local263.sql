-- ========== OUTPUT COLUMN SPEC ==========
-- 1. status          : 'strong' or 'soft' — the model status category
-- 2. L1_model        : the L1_model with highest occurrence count for that status
-- 3. occurrence_count : how many (name, version) models are associated with that L1_model+status
-- ========================================

-- INTERPRETATION: For each (name, version) model, determine its status:
--   'strong' = any step where max non-Stack test_score < Stack test_score
--   'soft'   = not strong, but any step where max non-Stack test_score = Stack test_score
-- Then count how many models per (status, L1_model), and return the L1_model
-- with the highest count for each status.

-- EXPECTED: 2 rows (one per status: 'strong', 'soft')

WITH step_scores AS (
    -- For each (name, version, step), compute stack_score and max non-stack score
    SELECT
        name, version, step,
        MAX(CASE WHEN model = 'Stack' THEN test_score END) AS stack_score,
        MAX(CASE WHEN model != 'Stack' THEN test_score END) AS max_non_stack_score
    FROM model_score
    GROUP BY name, version, step
),
model_status AS (
    -- Determine model-level status: 'strong' takes precedence over 'soft'
    SELECT
        name, version,
        CASE
            WHEN MAX(CASE WHEN max_non_stack_score < stack_score THEN 1 ELSE 0 END) = 1 THEN 'strong'
            WHEN MAX(CASE WHEN max_non_stack_score = stack_score THEN 1 ELSE 0 END) = 1 THEN 'soft'
        END AS status
    FROM step_scores
    WHERE stack_score IS NOT NULL AND max_non_stack_score IS NOT NULL
    GROUP BY name, version
),
model_with_l1 AS (
    -- Join with solution_ext to get L1_model at the (name, version) level
    SELECT ms.name, ms.version, ms.status, se.L1_model
    FROM model_status ms
    JOIN solution_ext se ON ms.name = se.name AND ms.version = se.version
    WHERE ms.status IS NOT NULL
),
l1_counts AS (
    -- Count L1_model occurrences per status
    SELECT status, L1_model, COUNT(*) AS occurrence_count
    FROM model_with_l1
    GROUP BY status, L1_model
),
max_per_status AS (
    -- Find the maximum count per status
    SELECT status, MAX(occurrence_count) AS max_count
    FROM l1_counts
    GROUP BY status
)
SELECT lc.status, lc.L1_model, lc.occurrence_count
FROM l1_counts lc
JOIN max_per_status mps ON lc.status = mps.status AND lc.occurrence_count = mps.max_count
ORDER BY lc.status;
