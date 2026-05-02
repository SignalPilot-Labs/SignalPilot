WITH cn_dates AS (
    SELECT DISTINCT insert_date AS entry_date
    FROM cities
    WHERE country_code_2 = 'cn'
      AND insert_date >= '2021-07-01'
      AND insert_date <= '2021-07-31'
),
streaks AS (
    SELECT entry_date,
           julianday(entry_date) - ROW_NUMBER() OVER (ORDER BY entry_date) AS streak_key
    FROM cn_dates
),
streak_lengths AS (
    SELECT streak_key, COUNT(*) AS streak_len
    FROM streaks
    GROUP BY streak_key
),
min_max AS (
    SELECT MIN(streak_len) AS min_len, MAX(streak_len) AS max_len
    FROM streak_lengths
),
target_dates AS (
    SELECT s.entry_date
    FROM streaks s
    JOIN streak_lengths sl ON s.streak_key = sl.streak_key
    JOIN min_max m ON sl.streak_len = m.min_len OR sl.streak_len = m.max_len
),
first_city AS (
    SELECT insert_date,
           CASE
             WHEN MIN(city_name) LIKE 'a%' THEN REPLACE('#'||MIN(city_name),'#a','A')
             WHEN MIN(city_name) LIKE 'b%' THEN REPLACE('#'||MIN(city_name),'#b','B')
             WHEN MIN(city_name) LIKE 'c%' THEN REPLACE('#'||MIN(city_name),'#c','C')
             WHEN MIN(city_name) LIKE 'd%' THEN REPLACE('#'||MIN(city_name),'#d','D')
             WHEN MIN(city_name) LIKE 'e%' THEN REPLACE('#'||MIN(city_name),'#e','E')
             WHEN MIN(city_name) LIKE 'f%' THEN REPLACE('#'||MIN(city_name),'#f','F')
             WHEN MIN(city_name) LIKE 'g%' THEN REPLACE('#'||MIN(city_name),'#g','G')
             WHEN MIN(city_name) LIKE 'h%' THEN REPLACE('#'||MIN(city_name),'#h','H')
             WHEN MIN(city_name) LIKE 'i%' THEN REPLACE('#'||MIN(city_name),'#i','I')
             WHEN MIN(city_name) LIKE 'j%' THEN REPLACE('#'||MIN(city_name),'#j','J')
             WHEN MIN(city_name) LIKE 'k%' THEN REPLACE('#'||MIN(city_name),'#k','K')
             WHEN MIN(city_name) LIKE 'l%' THEN REPLACE('#'||MIN(city_name),'#l','L')
             WHEN MIN(city_name) LIKE 'm%' THEN REPLACE('#'||MIN(city_name),'#m','M')
             WHEN MIN(city_name) LIKE 'n%' THEN REPLACE('#'||MIN(city_name),'#n','N')
             WHEN MIN(city_name) LIKE 'o%' THEN REPLACE('#'||MIN(city_name),'#o','O')
             WHEN MIN(city_name) LIKE 'p%' THEN REPLACE('#'||MIN(city_name),'#p','P')
             WHEN MIN(city_name) LIKE 'q%' THEN REPLACE('#'||MIN(city_name),'#q','Q')
             WHEN MIN(city_name) LIKE 'r%' THEN REPLACE('#'||MIN(city_name),'#r','R')
             WHEN MIN(city_name) LIKE 's%' THEN REPLACE('#'||MIN(city_name),'#s','S')
             WHEN MIN(city_name) LIKE 't%' THEN REPLACE('#'||MIN(city_name),'#t','T')
             WHEN MIN(city_name) LIKE 'u%' THEN REPLACE('#'||MIN(city_name),'#u','U')
             WHEN MIN(city_name) LIKE 'v%' THEN REPLACE('#'||MIN(city_name),'#v','V')
             WHEN MIN(city_name) LIKE 'w%' THEN REPLACE('#'||MIN(city_name),'#w','W')
             WHEN MIN(city_name) LIKE 'x%' THEN REPLACE('#'||MIN(city_name),'#x','X')
             WHEN MIN(city_name) LIKE 'y%' THEN REPLACE('#'||MIN(city_name),'#y','Y')
             WHEN MIN(city_name) LIKE 'z%' THEN REPLACE('#'||MIN(city_name),'#z','Z')
             ELSE MIN(city_name)
           END AS city_name
    FROM cities
    WHERE country_code_2 = 'cn'
      AND insert_date >= '2021-07-01'
      AND insert_date <= '2021-07-31'
    GROUP BY insert_date
)
SELECT td.entry_date, fc.city_name
FROM target_dates td
JOIN first_city fc ON td.entry_date = fc.insert_date
ORDER BY td.entry_date
