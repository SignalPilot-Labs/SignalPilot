-- ========== OUTPUT COLUMN SPEC ==========
-- 1. BowlerID       : bowler's unique ID
-- 2. BowlerFirstName: bowler's first name
-- 3. BowlerLastName : bowler's last name
-- 4. MatchID        : match number
-- 5. GameNumber     : game number within the match
-- 6. HandiCapScore  : handicap score (must be ≤190 AND WonGame=1)
-- 7. TourneyDate    : date of the tournament
-- 8. TourneyLocation: location name (one of the 3 venues)
-- ==========================================
-- EXPECTED: Small set of rows — bowlers qualifying at all 3 venues, specific game records only
-- INTERPRETATION: Find bowlers who each have at least one winning game (WonGame=1) with
--   HandiCapScore<=190 at Thunderbird Lanes AND Totem Lanes AND Bolero Lanes.
--   Return ONLY those specific game records (won + ≤190 + at those 3 venues) for qualifying bowlers.

WITH qualifying_games AS (
    SELECT
        bs.BowlerID,
        bs.MatchID,
        bs.GameNumber,
        bs.HandiCapScore,
        t.TourneyDate,
        t.TourneyLocation
    FROM Bowler_Scores bs
    JOIN Tourney_Matches tm ON bs.MatchID = tm.MatchID
    JOIN Tournaments t ON tm.TourneyID = t.TourneyID
    WHERE bs.WonGame = 1
      AND bs.HandiCapScore <= 190
      AND t.TourneyLocation IN ('Thunderbird Lanes', 'Totem Lanes', 'Bolero Lanes')
),
bowlers_at_all_three AS (
    SELECT BowlerID
    FROM qualifying_games
    GROUP BY BowlerID
    HAVING COUNT(DISTINCT TourneyLocation) = 3
)
SELECT
    b.BowlerID,
    b.BowlerFirstName,
    b.BowlerLastName,
    qg.MatchID,
    qg.GameNumber,
    qg.HandiCapScore,
    qg.TourneyDate,
    qg.TourneyLocation
FROM qualifying_games qg
JOIN bowlers_at_all_three bat ON qg.BowlerID = bat.BowlerID
JOIN Bowlers b ON qg.BowlerID = b.BowlerID
ORDER BY b.BowlerID, qg.MatchID, qg.GameNumber;
