-- EXPECTED: 10 rows (first 10 alphabetical words starting with 'r', 4-5 chars, with at least 1 anagram)
-- INTERPRETATION: Find words that are 4-5 chars long, start with lowercase 'r', and have at
-- least one other word in word_list that is a case-sensitive anagram (same length, same chars).
-- Count the number of such anagrams for each qualifying word.

-- ========== OUTPUT COLUMN SPEC ==========
-- 1. words         : the word (4-5 chars, starts with 'r', natural identifier)
-- 2. anagram_count : count of other words in word_list that are case-sensitive anagrams
-- ========================================

WITH all_sigs AS (
  SELECT DISTINCT words, (
    SELECT GROUP_CONCAT(ch, '')
    FROM (
      SELECT substr(words, pos, 1) as ch
      FROM (SELECT 1 as pos UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4 UNION ALL SELECT 5)
      WHERE pos <= length(words)
      ORDER BY ch
    )
  ) as signature
  FROM word_list
  WHERE length(words) BETWEEN 4 AND 5
),
sig_counts AS (
  SELECT signature, COUNT(*) as word_count
  FROM all_sigs
  GROUP BY signature
  HAVING COUNT(*) > 1
)
SELECT w.words, (sc.word_count - 1) as anagram_count
FROM all_sigs w
JOIN sig_counts sc ON w.signature = sc.signature
WHERE substr(w.words, 1, 1) = 'r'
ORDER BY w.words
LIMIT 10;
