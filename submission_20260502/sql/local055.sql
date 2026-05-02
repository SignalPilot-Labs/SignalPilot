-- INTERPRETATION: Find the top-selling artist (highest total revenue from album tracks,
-- tie-broken alphabetically) and lowest-selling artist (lowest total revenue, tie-broken
-- alphabetically). For each artist, compute per-customer spend on that artist's albums.
-- Then return the absolute difference between the two group averages.

-- EXPECTED: 1 row

WITH artist_sales AS (
    SELECT
        ar.ArtistId,
        ar.Name,
        SUM(ii.UnitPrice * ii.Quantity) AS total_sales
    FROM artists ar
    JOIN albums al ON ar.ArtistId = al.ArtistId
    JOIN tracks t ON al.AlbumId = t.AlbumId
    JOIN invoice_items ii ON t.TrackId = ii.TrackId
    GROUP BY ar.ArtistId, ar.Name
),
top_artist AS (
    SELECT ArtistId, Name
    FROM artist_sales
    ORDER BY total_sales DESC, Name ASC
    LIMIT 1
),
lowest_artist AS (
    SELECT ArtistId, Name
    FROM artist_sales
    ORDER BY total_sales ASC, Name ASC
    LIMIT 1
),
customer_spend_top AS (
    SELECT
        i.CustomerId,
        SUM(ii.UnitPrice * ii.Quantity) AS spend
    FROM top_artist ta
    JOIN albums al ON ta.ArtistId = al.ArtistId
    JOIN tracks t ON al.AlbumId = t.AlbumId
    JOIN invoice_items ii ON t.TrackId = ii.TrackId
    JOIN invoices i ON ii.InvoiceId = i.InvoiceId
    GROUP BY i.CustomerId
),
customer_spend_lowest AS (
    SELECT
        i.CustomerId,
        SUM(ii.UnitPrice * ii.Quantity) AS spend
    FROM lowest_artist la
    JOIN albums al ON la.ArtistId = al.ArtistId
    JOIN tracks t ON al.AlbumId = t.AlbumId
    JOIN invoice_items ii ON t.TrackId = ii.TrackId
    JOIN invoices i ON ii.InvoiceId = i.InvoiceId
    GROUP BY i.CustomerId
)
SELECT
    (SELECT AVG(spend) FROM customer_spend_top) AS avg_spend_top_artist,
    (SELECT AVG(spend) FROM customer_spend_lowest) AS avg_spend_lowest_artist,
    ABS(
        (SELECT AVG(spend) FROM customer_spend_top) -
        (SELECT AVG(spend) FROM customer_spend_lowest)
    ) AS absolute_difference
