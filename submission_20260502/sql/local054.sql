-- ========== OUTPUT COLUMN SPEC ==========
-- 1. FirstName   : customer's first name
-- 2. total_spent : total amount spent by customer on albums by the best-selling artist
-- ========================================

-- INTERPRETATION: Find the best-selling artist by total revenue (SUM of UnitPrice*Quantity),
-- then return first names and total spending for customers who spent < $1 on that artist's albums.
-- EXPECTED: small number of rows (customers with < $1 total spent on best-selling artist albums)

WITH best_artist AS (
    SELECT ar.ArtistId
    FROM invoice_items ii
    JOIN tracks t ON ii.TrackId = t.TrackId
    JOIN albums al ON t.AlbumId = al.AlbumId
    JOIN artists ar ON al.ArtistId = ar.ArtistId
    GROUP BY ar.ArtistId, ar.Name
    ORDER BY SUM(ii.UnitPrice * ii.Quantity) DESC
    LIMIT 1
),
customer_spending AS (
    SELECT
        c.CustomerId,
        c.FirstName,
        SUM(ii.UnitPrice * ii.Quantity) AS total_spent
    FROM invoice_items ii
    JOIN invoices inv ON ii.InvoiceId = inv.InvoiceId
    JOIN customers c ON inv.CustomerId = c.CustomerId
    JOIN tracks t ON ii.TrackId = t.TrackId
    JOIN albums al ON t.AlbumId = al.AlbumId
    WHERE al.ArtistId = (SELECT ArtistId FROM best_artist)
    GROUP BY c.CustomerId, c.FirstName
)
SELECT FirstName, total_spent
FROM customer_spending
WHERE total_spent < 1.0
ORDER BY FirstName
