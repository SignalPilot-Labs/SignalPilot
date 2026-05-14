-- ============================================================
-- dbt_learn: Sample data warehouse for learning dbt
-- ============================================================
-- Creates a realistic e-commerce data warehouse with:
--   raw_ecommerce  — transactional source data (orders, payments, etc.)
--   raw_marketing   — marketing/attribution source data
--   raw_support     — customer support ticket data
--   raw_product     — product catalog data
--
-- Use these raw schemas as dbt sources, then build:
--   staging models, intermediate models, marts, metrics
-- ============================================================

-- Create the database
-- (Run this part separately if needed)
-- CREATE DATABASE dbt_learn;

-- ============================================================
-- SCHEMA: raw_ecommerce
-- ============================================================
CREATE SCHEMA IF NOT EXISTS raw_ecommerce;

-- Customers
CREATE TABLE raw_ecommerce.customers (
    customer_id SERIAL PRIMARY KEY,
    first_name VARCHAR(50) NOT NULL,
    last_name VARCHAR(50) NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    phone VARCHAR(20),
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    country VARCHAR(2) NOT NULL,
    city VARCHAR(100),
    state VARCHAR(50),
    zip_code VARCHAR(20),
    is_active BOOLEAN DEFAULT true,
    customer_segment VARCHAR(20) -- 'new', 'returning', 'vip', 'churned'
);

-- Products
CREATE TABLE raw_ecommerce.products (
    product_id SERIAL PRIMARY KEY,
    product_name VARCHAR(200) NOT NULL,
    category_id INT NOT NULL,
    subcategory VARCHAR(100),
    brand VARCHAR(100),
    sku VARCHAR(50) UNIQUE NOT NULL,
    price_cents INT NOT NULL,
    cost_cents INT NOT NULL,
    weight_grams INT,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

-- Categories
CREATE TABLE raw_ecommerce.categories (
    category_id SERIAL PRIMARY KEY,
    category_name VARCHAR(100) NOT NULL,
    parent_category_id INT REFERENCES raw_ecommerce.categories(category_id),
    sort_order INT DEFAULT 0
);

-- Orders
CREATE TABLE raw_ecommerce.orders (
    order_id SERIAL PRIMARY KEY,
    customer_id INT NOT NULL REFERENCES raw_ecommerce.customers(customer_id),
    order_date TIMESTAMP NOT NULL,
    status VARCHAR(20) NOT NULL, -- 'pending', 'processing', 'shipped', 'delivered', 'returned', 'cancelled'
    shipping_method VARCHAR(30),
    shipping_address_country VARCHAR(2),
    shipping_address_city VARCHAR(100),
    shipping_address_state VARCHAR(50),
    shipping_address_zip VARCHAR(20),
    discount_cents INT DEFAULT 0,
    tax_cents INT DEFAULT 0,
    shipping_cents INT DEFAULT 0,
    total_cents INT NOT NULL,
    coupon_code VARCHAR(30),
    notes TEXT,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

-- Order items
CREATE TABLE raw_ecommerce.order_items (
    order_item_id SERIAL PRIMARY KEY,
    order_id INT NOT NULL REFERENCES raw_ecommerce.orders(order_id),
    product_id INT NOT NULL REFERENCES raw_ecommerce.products(product_id),
    quantity INT NOT NULL DEFAULT 1,
    unit_price_cents INT NOT NULL,
    discount_cents INT DEFAULT 0,
    total_cents INT NOT NULL
);

-- Payments
CREATE TABLE raw_ecommerce.payments (
    payment_id SERIAL PRIMARY KEY,
    order_id INT NOT NULL REFERENCES raw_ecommerce.orders(order_id),
    payment_method VARCHAR(30) NOT NULL, -- 'credit_card', 'debit_card', 'pix', 'boleto', 'paypal', 'apple_pay'
    amount_cents INT NOT NULL,
    status VARCHAR(20) NOT NULL, -- 'pending', 'authorized', 'captured', 'failed', 'refunded'
    gateway_reference VARCHAR(100),
    processed_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL
);

-- Shipping events (for tracking)
CREATE TABLE raw_ecommerce.shipping_events (
    event_id SERIAL PRIMARY KEY,
    order_id INT NOT NULL REFERENCES raw_ecommerce.orders(order_id),
    carrier VARCHAR(50),
    tracking_number VARCHAR(100),
    event_type VARCHAR(30) NOT NULL, -- 'label_created', 'picked_up', 'in_transit', 'out_for_delivery', 'delivered', 'returned'
    event_timestamp TIMESTAMP NOT NULL,
    location VARCHAR(200)
);

-- Product reviews
CREATE TABLE raw_ecommerce.reviews (
    review_id SERIAL PRIMARY KEY,
    product_id INT NOT NULL REFERENCES raw_ecommerce.products(product_id),
    customer_id INT NOT NULL REFERENCES raw_ecommerce.customers(customer_id),
    order_id INT REFERENCES raw_ecommerce.orders(order_id),
    rating INT NOT NULL CHECK (rating BETWEEN 1 AND 5),
    title VARCHAR(200),
    body TEXT,
    is_verified_purchase BOOLEAN DEFAULT false,
    created_at TIMESTAMP NOT NULL
);

-- Inventory snapshots (daily)
CREATE TABLE raw_ecommerce.inventory_snapshots (
    snapshot_id SERIAL PRIMARY KEY,
    product_id INT NOT NULL REFERENCES raw_ecommerce.products(product_id),
    warehouse_id INT NOT NULL,
    quantity_on_hand INT NOT NULL,
    quantity_reserved INT DEFAULT 0,
    snapshot_date DATE NOT NULL,
    UNIQUE(product_id, warehouse_id, snapshot_date)
);

-- Warehouses
CREATE TABLE raw_ecommerce.warehouses (
    warehouse_id SERIAL PRIMARY KEY,
    warehouse_name VARCHAR(100) NOT NULL,
    country VARCHAR(2) NOT NULL,
    city VARCHAR(100),
    state VARCHAR(50),
    is_active BOOLEAN DEFAULT true
);

-- ============================================================
-- SCHEMA: raw_marketing
-- ============================================================
CREATE SCHEMA IF NOT EXISTS raw_marketing;

-- Ad campaigns
CREATE TABLE raw_marketing.campaigns (
    campaign_id SERIAL PRIMARY KEY,
    campaign_name VARCHAR(200) NOT NULL,
    channel VARCHAR(30) NOT NULL, -- 'google_ads', 'facebook', 'instagram', 'tiktok', 'email', 'sms', 'organic'
    campaign_type VARCHAR(30), -- 'awareness', 'consideration', 'conversion', 'retention'
    start_date DATE NOT NULL,
    end_date DATE,
    budget_cents INT,
    status VARCHAR(20) DEFAULT 'active', -- 'draft', 'active', 'paused', 'completed'
    created_at TIMESTAMP NOT NULL
);

-- Daily campaign spend
CREATE TABLE raw_marketing.campaign_spend (
    spend_id SERIAL PRIMARY KEY,
    campaign_id INT NOT NULL REFERENCES raw_marketing.campaigns(campaign_id),
    spend_date DATE NOT NULL,
    spend_cents INT NOT NULL,
    impressions INT DEFAULT 0,
    clicks INT DEFAULT 0,
    conversions INT DEFAULT 0,
    UNIQUE(campaign_id, spend_date)
);

-- Website sessions (attribution)
CREATE TABLE raw_marketing.web_sessions (
    session_id VARCHAR(36) PRIMARY KEY,
    visitor_id VARCHAR(36) NOT NULL,
    customer_id INT, -- NULL if anonymous
    session_start TIMESTAMP NOT NULL,
    session_end TIMESTAMP,
    landing_page VARCHAR(500),
    exit_page VARCHAR(500),
    page_views INT DEFAULT 1,
    utm_source VARCHAR(100),
    utm_medium VARCHAR(100),
    utm_campaign VARCHAR(200),
    utm_content VARCHAR(200),
    device_type VARCHAR(20), -- 'desktop', 'mobile', 'tablet'
    browser VARCHAR(50),
    country VARCHAR(2),
    referrer VARCHAR(500),
    converted BOOLEAN DEFAULT false,
    order_id INT
);

-- Email events
CREATE TABLE raw_marketing.email_events (
    event_id SERIAL PRIMARY KEY,
    campaign_id INT REFERENCES raw_marketing.campaigns(campaign_id),
    customer_id INT NOT NULL,
    email VARCHAR(100) NOT NULL,
    event_type VARCHAR(20) NOT NULL, -- 'sent', 'delivered', 'opened', 'clicked', 'bounced', 'unsubscribed', 'complained'
    event_timestamp TIMESTAMP NOT NULL,
    link_url VARCHAR(500),
    subject_line VARCHAR(200)
);

-- ============================================================
-- SCHEMA: raw_support
-- ============================================================
CREATE SCHEMA IF NOT EXISTS raw_support;

-- Support tickets
CREATE TABLE raw_support.tickets (
    ticket_id SERIAL PRIMARY KEY,
    customer_id INT NOT NULL,
    order_id INT,
    channel VARCHAR(20) NOT NULL, -- 'email', 'chat', 'phone', 'social'
    category VARCHAR(50), -- 'shipping', 'returns', 'product_issue', 'billing', 'general'
    subcategory VARCHAR(50),
    priority VARCHAR(10) DEFAULT 'medium', -- 'low', 'medium', 'high', 'urgent'
    status VARCHAR(20) NOT NULL, -- 'open', 'in_progress', 'waiting_customer', 'resolved', 'closed'
    subject VARCHAR(300),
    description TEXT,
    assigned_agent_id INT,
    first_response_at TIMESTAMP,
    resolved_at TIMESTAMP,
    satisfaction_score INT CHECK (satisfaction_score BETWEEN 1 AND 5),
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

-- Support agents
CREATE TABLE raw_support.agents (
    agent_id SERIAL PRIMARY KEY,
    agent_name VARCHAR(100) NOT NULL,
    team VARCHAR(50),
    tier VARCHAR(10), -- 'L1', 'L2', 'L3'
    is_active BOOLEAN DEFAULT true,
    hire_date DATE
);

-- Ticket messages
CREATE TABLE raw_support.ticket_messages (
    message_id SERIAL PRIMARY KEY,
    ticket_id INT NOT NULL REFERENCES raw_support.tickets(ticket_id),
    sender_type VARCHAR(10) NOT NULL, -- 'customer', 'agent', 'system'
    sender_id INT,
    message_body TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL
);

-- ============================================================
-- SCHEMA: raw_product (product catalog / enrichment)
-- ============================================================
CREATE SCHEMA IF NOT EXISTS raw_product;

-- Product attributes (EAV-style, common in real data)
CREATE TABLE raw_product.product_attributes (
    attribute_id SERIAL PRIMARY KEY,
    product_id INT NOT NULL,
    attribute_name VARCHAR(100) NOT NULL,
    attribute_value VARCHAR(500),
    UNIQUE(product_id, attribute_name)
);

-- Price history
CREATE TABLE raw_product.price_history (
    price_history_id SERIAL PRIMARY KEY,
    product_id INT NOT NULL,
    old_price_cents INT,
    new_price_cents INT NOT NULL,
    changed_at TIMESTAMP NOT NULL,
    reason VARCHAR(50) -- 'promotion', 'cost_increase', 'competitive', 'clearance'
);

-- Supplier info
CREATE TABLE raw_product.suppliers (
    supplier_id SERIAL PRIMARY KEY,
    supplier_name VARCHAR(200) NOT NULL,
    country VARCHAR(2),
    lead_time_days INT,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP NOT NULL
);

CREATE TABLE raw_product.product_suppliers (
    product_id INT NOT NULL,
    supplier_id INT NOT NULL REFERENCES raw_product.suppliers(supplier_id),
    is_primary BOOLEAN DEFAULT false,
    supplier_sku VARCHAR(50),
    cost_cents INT,
    PRIMARY KEY (product_id, supplier_id)
);


-- ============================================================
-- DATA POPULATION
-- ============================================================

-- Categories
INSERT INTO raw_ecommerce.categories (category_id, category_name, parent_category_id, sort_order) VALUES
(1, 'Electronics', NULL, 1),
(2, 'Clothing', NULL, 2),
(3, 'Home & Garden', NULL, 3),
(4, 'Sports & Outdoors', NULL, 4),
(5, 'Books', NULL, 5),
(6, 'Smartphones', 1, 1),
(7, 'Laptops', 1, 2),
(8, 'Audio', 1, 3),
(9, 'Accessories', 1, 4),
(10, 'Men''s', 2, 1),
(11, 'Women''s', 2, 2),
(12, 'Kids', 2, 3),
(13, 'Furniture', 3, 1),
(14, 'Kitchen', 3, 2),
(15, 'Garden', 3, 3),
(16, 'Fitness', 4, 1),
(17, 'Camping', 4, 2),
(18, 'Fiction', 5, 1),
(19, 'Non-Fiction', 5, 2),
(20, 'Technical', 5, 3);

-- Warehouses
INSERT INTO raw_ecommerce.warehouses (warehouse_id, warehouse_name, country, city, state, is_active) VALUES
(1, 'São Paulo Hub', 'BR', 'São Paulo', 'SP', true),
(2, 'Rio Distribution', 'BR', 'Rio de Janeiro', 'RJ', true),
(3, 'Curitiba South', 'BR', 'Curitiba', 'PR', true),
(4, 'Recife Northeast', 'BR', 'Recife', 'PE', true);

-- Products (50 products)
INSERT INTO raw_ecommerce.products (product_id, product_name, category_id, subcategory, brand, sku, price_cents, cost_cents, weight_grams, is_active, created_at, updated_at) VALUES
(1, 'Galaxy S24 Ultra', 6, 'Flagship', 'Samsung', 'SAM-S24U-256', 1299900, 780000, 233, true, '2024-01-15', '2024-01-15'),
(2, 'iPhone 15 Pro', 6, 'Flagship', 'Apple', 'APL-I15P-256', 1199900, 720000, 187, true, '2023-09-22', '2023-09-22'),
(3, 'Pixel 8', 6, 'Mid-range', 'Google', 'GOO-PX8-128', 699900, 420000, 187, true, '2023-10-12', '2023-10-12'),
(4, 'Moto G84', 6, 'Budget', 'Motorola', 'MOT-G84-128', 249900, 150000, 168, true, '2023-11-01', '2023-11-01'),
(5, 'MacBook Air M3', 7, 'Ultrabook', 'Apple', 'APL-MBA-M3', 1299900, 780000, 1240, true, '2024-03-08', '2024-03-08'),
(6, 'ThinkPad X1 Carbon', 7, 'Business', 'Lenovo', 'LEN-X1C-G12', 1799900, 1080000, 1120, true, '2024-01-20', '2024-01-20'),
(7, 'Dell XPS 15', 7, 'Premium', 'Dell', 'DEL-XPS15-32', 1599900, 960000, 1860, true, '2024-02-10', '2024-02-10'),
(8, 'AirPods Pro 2', 8, 'TWS', 'Apple', 'APL-APP2', 249900, 125000, 51, true, '2023-09-22', '2023-09-22'),
(9, 'Sony WH-1000XM5', 8, 'Over-ear', 'Sony', 'SON-XM5-BLK', 349900, 175000, 250, true, '2023-05-15', '2023-05-15'),
(10, 'JBL Flip 6', 8, 'Speaker', 'JBL', 'JBL-FLIP6-BLU', 129900, 65000, 550, true, '2023-03-10', '2023-03-10'),
(11, 'USB-C Hub 7-in-1', 9, 'Hubs', 'Anker', 'ANK-HUB7', 49900, 20000, 120, true, '2023-06-01', '2023-06-01'),
(12, 'Mechanical Keyboard', 9, 'Input', 'Keychron', 'KEY-K2V2-RGB', 99900, 45000, 680, true, '2023-07-15', '2023-07-15'),
(13, 'Logitech MX Master 3S', 9, 'Input', 'Logitech', 'LOG-MXM3S', 99900, 50000, 141, true, '2023-04-20', '2023-04-20'),
(14, 'Men''s Classic Polo', 10, 'Shirts', 'Lacoste', 'LAC-POLO-M-BLU', 89900, 36000, 200, true, '2024-01-05', '2024-01-05'),
(15, 'Slim Fit Jeans', 10, 'Pants', 'Levi''s', 'LEV-511-32-32', 79900, 32000, 700, true, '2024-02-01', '2024-02-01'),
(16, 'Running Sneakers', 10, 'Shoes', 'Nike', 'NIK-PEGASUS-42', 139900, 56000, 280, true, '2024-03-01', '2024-03-01'),
(17, 'Women''s Maxi Dress', 11, 'Dresses', 'Zara', 'ZAR-MAXI-S', 69900, 21000, 300, true, '2024-02-15', '2024-02-15'),
(18, 'Leather Handbag', 11, 'Bags', 'Michael Kors', 'MK-TOTE-BLK', 299900, 120000, 900, true, '2024-01-10', '2024-01-10'),
(19, 'Yoga Pants', 11, 'Activewear', 'Lululemon', 'LUL-ALIGN-M', 119900, 42000, 250, true, '2024-01-20', '2024-01-20'),
(20, 'Kids Sneakers', 12, 'Shoes', 'Adidas', 'ADI-KIDS-34', 59900, 24000, 200, true, '2024-03-10', '2024-03-10'),
(21, 'Ergonomic Office Chair', 13, 'Chairs', 'Herman Miller', 'HM-AERON-B', 1599900, 800000, 18000, true, '2023-08-01', '2023-08-01'),
(22, 'Standing Desk', 13, 'Desks', 'FlexiSpot', 'FLX-E7-160', 599900, 300000, 35000, true, '2023-09-15', '2023-09-15'),
(23, 'Bookshelf', 13, 'Storage', 'IKEA', 'IKE-BILLY-WHT', 49900, 20000, 28000, true, '2023-06-01', '2023-06-01'),
(24, 'Air Fryer 5L', 14, 'Appliances', 'Philips', 'PHI-AF-5L', 149900, 60000, 4500, true, '2023-10-01', '2023-10-01'),
(25, 'Chef''s Knife Set', 14, 'Cutlery', 'Tramontina', 'TRM-CHEF-6PC', 89900, 36000, 1200, true, '2023-07-20', '2023-07-20'),
(26, 'Espresso Machine', 14, 'Appliances', 'Nespresso', 'NSP-VERTUO-NXT', 199900, 80000, 4000, true, '2023-11-15', '2023-11-15'),
(27, 'Robot Vacuum', 14, 'Appliances', 'iRobot', 'IRB-ROOMBA-J7', 499900, 200000, 3400, true, '2023-08-10', '2023-08-10'),
(28, 'Garden Tool Set', 15, 'Tools', 'Tramontina', 'TRM-GARDEN-5PC', 39900, 16000, 2500, true, '2024-01-15', '2024-01-15'),
(29, 'LED Grow Light', 15, 'Lighting', 'Spider Farmer', 'SPF-SF1000', 119900, 48000, 2400, true, '2023-12-01', '2023-12-01'),
(30, 'Adjustable Dumbbells', 16, 'Weights', 'Bowflex', 'BWF-552-PAIR', 349900, 175000, 23000, true, '2023-05-01', '2023-05-01'),
(31, 'Yoga Mat Premium', 16, 'Mats', 'Manduka', 'MAN-PRO-6MM', 89900, 36000, 2500, true, '2023-06-15', '2023-06-15'),
(32, 'Fitness Tracker', 16, 'Wearables', 'Fitbit', 'FIT-CHARGE6', 159900, 64000, 37, true, '2023-10-15', '2023-10-15'),
(33, 'Running Watch', 16, 'Wearables', 'Garmin', 'GAR-FR265', 449900, 225000, 47, true, '2024-01-01', '2024-01-01'),
(34, '2-Person Tent', 17, 'Tents', 'Coleman', 'COL-TENT-2P', 199900, 80000, 3200, true, '2023-09-01', '2023-09-01'),
(35, 'Sleeping Bag', 17, 'Sleep', 'Deuter', 'DEU-SB-0C', 149900, 60000, 1400, true, '2023-08-15', '2023-08-15'),
(36, 'Hiking Backpack 50L', 17, 'Packs', 'Osprey', 'OSP-ATMOS-50', 299900, 150000, 1480, true, '2024-02-01', '2024-02-01'),
(37, 'Dune', 18, 'Sci-Fi', 'Frank Herbert', 'BK-DUNE-PB', 4990, 2000, 350, true, '2023-01-01', '2023-01-01'),
(38, 'Project Hail Mary', 18, 'Sci-Fi', 'Andy Weir', 'BK-PHM-PB', 5990, 2400, 320, true, '2023-01-15', '2023-01-15'),
(39, 'Atomic Habits', 19, 'Self-Help', 'James Clear', 'BK-AH-PB', 4490, 1800, 280, true, '2023-02-01', '2023-02-01'),
(40, 'Sapiens', 19, 'History', 'Yuval Harari', 'BK-SAP-PB', 5490, 2200, 420, true, '2023-02-15', '2023-02-15'),
(41, 'Clean Code', 20, 'Software', 'Robert C. Martin', 'BK-CC-PB', 6990, 2800, 380, true, '2023-03-01', '2023-03-01'),
(42, 'Designing Data-Intensive Apps', 20, 'Software', 'Martin Kleppmann', 'BK-DDIA-PB', 7990, 3200, 450, true, '2023-03-15', '2023-03-15'),
(43, 'The Analytics Engineering Guide', 20, 'Data', 'dbt Labs', 'BK-AEG-PB', 4990, 2000, 300, true, '2023-04-01', '2023-04-01'),
(44, 'Wireless Charger Pad', 9, 'Charging', 'Anker', 'ANK-QI-15W', 29900, 12000, 80, true, '2023-05-01', '2023-05-01'),
(45, 'Monitor 27" 4K', 9, 'Displays', 'LG', 'LG-27UK850', 449900, 225000, 6200, true, '2023-06-10', '2023-06-10'),
(46, 'Webcam HD', 9, 'Video', 'Logitech', 'LOG-C920S', 79900, 32000, 162, true, '2023-04-15', '2023-04-15'),
(47, 'Noise Cancelling Earbuds', 8, 'TWS', 'Bose', 'BOS-QC-ULTRA', 299900, 150000, 62, true, '2024-01-05', '2024-01-05'),
(48, 'Smart Watch', 9, 'Wearables', 'Apple', 'APL-AW9-45', 449900, 225000, 42, true, '2023-09-22', '2023-09-22'),
(49, 'Portable SSD 1TB', 9, 'Storage', 'Samsung', 'SAM-T7-1TB', 99900, 50000, 58, true, '2023-07-01', '2023-07-01'),
(50, 'Power Bank 20000mAh', 9, 'Charging', 'Anker', 'ANK-PB-20K', 49900, 20000, 340, true, '2023-08-01', '2023-08-01');

-- Customers (200 customers)
INSERT INTO raw_ecommerce.customers (customer_id, first_name, last_name, email, phone, created_at, updated_at, country, city, state, zip_code, is_active, customer_segment)
SELECT
    s.id,
    (ARRAY['João','Maria','Pedro','Ana','Lucas','Juliana','Carlos','Fernanda','Rafael','Camila',
           'Bruno','Larissa','Diego','Beatriz','Gustavo','Isabela','Thiago','Amanda','Felipe','Gabriela',
           'André','Patricia','Marcos','Letícia','Daniel','Carolina','Rodrigo','Mariana','Leonardo','Tatiana',
           'Mateus','Bruna','Eduardo','Aline','Alexandre','Priscila','Victor','Raquel','Henrique','Natália',
           'Renato','Daniela','Vinícius','Luana','Fábio','Vanessa','Miguel','Helena','Gabriel','Sofia'])[((s.id - 1) % 50) + 1],
    (ARRAY['Silva','Santos','Oliveira','Souza','Lima','Pereira','Costa','Ferreira','Rodrigues','Almeida',
           'Nascimento','Carvalho','Araújo','Ribeiro','Cardoso','Gomes','Martins','Barbosa','Rocha','Dias',
           'Moreira','Mendes','Nunes','Barros','Freitas','Medeiros','Batista','Campos','Teixeira','Vieira',
           'Monteiro','Correia','Pinto','Reis','Fernandes','Melo','Castro','Gonçalves','Ramos','Moura',
           'Lopes','Marques','Andrade','Cunha','Tavares','Azevedo','Sampaio','Miranda','Coelho','Cruz'])[((s.id - 1) % 50) + 1],
    'customer' || s.id || '@example.com',
    '+55119' || LPAD(((s.id * 7919) % 100000000)::TEXT, 8, '0'),
    TIMESTAMP '2023-01-01' + (random() * INTERVAL '500 days'),
    TIMESTAMP '2023-06-01' + (random() * INTERVAL '400 days'),
    CASE WHEN random() < 0.9 THEN 'BR' WHEN random() < 0.5 THEN 'US' ELSE 'PT' END,
    (ARRAY['São Paulo','Rio de Janeiro','Belo Horizonte','Curitiba','Porto Alegre','Salvador','Recife','Fortaleza','Brasília','Goiânia',
           'Campinas','Florianópolis','Manaus','Belém','Vitória'])[((s.id - 1) % 15) + 1],
    (ARRAY['SP','RJ','MG','PR','RS','BA','PE','CE','DF','GO','SP','SC','AM','PA','ES'])[((s.id - 1) % 15) + 1],
    LPAD(((s.id * 3571) % 99999)::TEXT, 5, '0') || '-' || LPAD(((s.id * 1117) % 999)::TEXT, 3, '0'),
    CASE WHEN random() > 0.05 THEN true ELSE false END,
    (ARRAY['new','returning','returning','vip','churned'])[((s.id * 31) % 5) + 1]
FROM generate_series(1, 200) AS s(id);

-- Orders (2000 orders across 18 months)
INSERT INTO raw_ecommerce.orders (order_id, customer_id, order_date, status, shipping_method, shipping_address_country, shipping_address_city, shipping_address_state, shipping_address_zip, discount_cents, tax_cents, shipping_cents, total_cents, coupon_code, created_at, updated_at)
SELECT
    s.id,
    ((s.id * 7) % 200) + 1,
    TIMESTAMP '2023-06-01' + ((s.id * 7919) % 548) * INTERVAL '1 day' + ((s.id * 127) % 24) * INTERVAL '1 hour',
    (ARRAY['delivered','delivered','delivered','delivered','shipped','processing','pending','returned','cancelled'])[((s.id * 13) % 9) + 1],
    (ARRAY['standard','standard','express','express','same_day','free'])[((s.id * 17) % 6) + 1],
    CASE WHEN random() < 0.9 THEN 'BR' ELSE 'US' END,
    (ARRAY['São Paulo','Rio de Janeiro','Belo Horizonte','Curitiba','Porto Alegre','Salvador','Recife','Fortaleza','Brasília','Goiânia'])[((s.id * 11) % 10) + 1],
    (ARRAY['SP','RJ','MG','PR','RS','BA','PE','CE','DF','GO'])[((s.id * 11) % 10) + 1],
    LPAD(((s.id * 2971) % 99999)::TEXT, 5, '0') || '-000',
    CASE WHEN (s.id % 5) = 0 THEN ((s.id * 37) % 5000) + 500 ELSE 0 END,
    ((s.id * 43) % 15000) + 500,
    CASE WHEN (s.id % 3) = 0 THEN 0 ELSE ((s.id * 19) % 3000) + 500 END,
    ((s.id * 89) % 300000) + 5000,
    CASE WHEN (s.id % 7) = 0 THEN 'SAVE' || ((s.id * 3) % 30) ELSE NULL END,
    TIMESTAMP '2023-06-01' + ((s.id * 7919) % 548) * INTERVAL '1 day',
    TIMESTAMP '2023-06-01' + ((s.id * 7919) % 548) * INTERVAL '1 day' + ((s.id * 31) % 5) * INTERVAL '1 day'
FROM generate_series(1, 2000) AS s(id);

-- Order items (avg ~2.5 items per order = ~5000 items)
INSERT INTO raw_ecommerce.order_items (order_id, product_id, quantity, unit_price_cents, discount_cents, total_cents)
SELECT
    o.order_id,
    ((o.order_id * p.n * 7) % 50) + 1 AS product_id,
    ((o.order_id * p.n * 3) % 3) + 1 AS quantity,
    pr.price_cents,
    CASE WHEN (o.order_id * p.n) % 4 = 0 THEN (pr.price_cents * 10) / 100 ELSE 0 END,
    (((o.order_id * p.n * 3) % 3) + 1) * pr.price_cents - CASE WHEN (o.order_id * p.n) % 4 = 0 THEN (pr.price_cents * 10) / 100 ELSE 0 END
FROM raw_ecommerce.orders o
CROSS JOIN generate_series(1, 3) AS p(n)
JOIN raw_ecommerce.products pr ON pr.product_id = ((o.order_id * p.n * 7) % 50) + 1
WHERE p.n <= ((o.order_id % 3) + 1);

-- Payments
INSERT INTO raw_ecommerce.payments (order_id, payment_method, amount_cents, status, gateway_reference, processed_at, created_at)
SELECT
    o.order_id,
    (ARRAY['credit_card','credit_card','credit_card','debit_card','pix','pix','boleto','paypal','apple_pay'])[((o.order_id * 17) % 9) + 1],
    o.total_cents,
    CASE
        WHEN o.status IN ('delivered','shipped','processing') THEN 'captured'
        WHEN o.status = 'pending' THEN 'authorized'
        WHEN o.status = 'cancelled' THEN 'failed'
        WHEN o.status = 'returned' THEN 'refunded'
        ELSE 'captured'
    END,
    'pay_' || md5(o.order_id::TEXT || 'ref'),
    o.order_date + INTERVAL '1 minute' * (o.order_id % 10),
    o.order_date
FROM raw_ecommerce.orders o;

-- Shipping events
INSERT INTO raw_ecommerce.shipping_events (order_id, carrier, tracking_number, event_type, event_timestamp, location)
SELECT
    o.order_id,
    (ARRAY['Correios','Jadlog','Loggi','Total Express'])[((o.order_id * 7) % 4) + 1],
    'BR' || LPAD(o.order_id::TEXT, 13, '0'),
    e.event_type,
    o.order_date + e.offset_hours * INTERVAL '1 hour',
    (ARRAY['São Paulo - SP','Curitiba - PR','Rio de Janeiro - RJ','Belo Horizonte - MG','Salvador - BA'])[((o.order_id + e.step) % 5) + 1]
FROM raw_ecommerce.orders o
CROSS JOIN (VALUES
    (1, 'label_created', 2),
    (2, 'picked_up', 24),
    (3, 'in_transit', 48),
    (4, 'out_for_delivery', 96),
    (5, 'delivered', 120)
) AS e(step, event_type, offset_hours)
WHERE o.status IN ('delivered','shipped','returned')
AND (o.status = 'delivered' OR e.step <= 3);

-- Reviews
INSERT INTO raw_ecommerce.reviews (product_id, customer_id, order_id, rating, title, body, is_verified_purchase, created_at)
SELECT
    oi.product_id,
    o.customer_id,
    o.order_id,
    GREATEST(1, LEAST(5, 3 + ((o.order_id * 7) % 5) - 2)),
    CASE GREATEST(1, LEAST(5, 3 + ((o.order_id * 7) % 5) - 2))
        WHEN 5 THEN (ARRAY['Excelente!','Adorei!','Superou expectativas','Perfeito','Recomendo muito'])[((o.order_id) % 5) + 1]
        WHEN 4 THEN (ARRAY['Muito bom','Gostei bastante','Boa qualidade','Entrega rápida','Bom custo-benefício'])[((o.order_id) % 5) + 1]
        WHEN 3 THEN (ARRAY['Regular','OK','Poderia ser melhor','Nada demais','Mediano'])[((o.order_id) % 5) + 1]
        WHEN 2 THEN (ARRAY['Decepcionante','Abaixo do esperado','Qualidade ruim','Não gostei','Fraco'])[((o.order_id) % 5) + 1]
        WHEN 1 THEN (ARRAY['Péssimo','Não comprem','Horrível','Defeituoso','Lixo'])[((o.order_id) % 5) + 1]
    END,
    'Avaliação do produto após uso.',
    true,
    o.order_date + INTERVAL '7 days' + ((o.order_id * 3) % 14) * INTERVAL '1 day'
FROM raw_ecommerce.orders o
JOIN raw_ecommerce.order_items oi ON oi.order_id = o.order_id
WHERE o.status = 'delivered'
AND (o.order_id % 3) = 0;

-- Inventory snapshots (daily for last 90 days, all products x all warehouses)
INSERT INTO raw_ecommerce.inventory_snapshots (product_id, warehouse_id, quantity_on_hand, quantity_reserved, snapshot_date)
SELECT
    p.product_id,
    w.warehouse_id,
    GREATEST(0, 100 + ((p.product_id * w.warehouse_id * d.d) % 200) - 100),
    GREATEST(0, ((p.product_id * w.warehouse_id * d.d) % 30)),
    CURRENT_DATE - (90 - d.d)
FROM raw_ecommerce.products p
CROSS JOIN raw_ecommerce.warehouses w
CROSS JOIN generate_series(1, 90) AS d(d);

-- ============================================================
-- Marketing data
-- ============================================================

-- Campaigns
INSERT INTO raw_marketing.campaigns (campaign_id, campaign_name, channel, campaign_type, start_date, end_date, budget_cents, status, created_at) VALUES
(1, 'Summer Sale 2024', 'google_ads', 'conversion', '2024-01-15', '2024-02-28', 5000000, 'completed', '2024-01-10'),
(2, 'Brand Awareness Q1', 'facebook', 'awareness', '2024-01-01', '2024-03-31', 3000000, 'completed', '2023-12-20'),
(3, 'Instagram Stories Push', 'instagram', 'consideration', '2024-02-01', '2024-04-30', 2000000, 'completed', '2024-01-25'),
(4, 'Newsletter Weekly', 'email', 'retention', '2023-06-01', NULL, 500000, 'active', '2023-05-20'),
(5, 'Google Shopping Feed', 'google_ads', 'conversion', '2023-06-01', NULL, 8000000, 'active', '2023-05-15'),
(6, 'TikTok Gen-Z Campaign', 'tiktok', 'awareness', '2024-03-01', '2024-06-30', 4000000, 'active', '2024-02-20'),
(7, 'Retargeting Display', 'google_ads', 'conversion', '2023-09-01', NULL, 3000000, 'active', '2023-08-25'),
(8, 'SMS Flash Sale', 'sms', 'conversion', '2024-04-01', '2024-04-03', 200000, 'completed', '2024-03-28'),
(9, 'Black Friday Prep', 'facebook', 'conversion', '2024-11-01', '2024-11-30', 10000000, 'completed', '2024-10-15'),
(10, 'Holiday Season Email', 'email', 'conversion', '2024-12-01', '2024-12-25', 1000000, 'completed', '2024-11-20'),
(11, 'New Year Clearance', 'google_ads', 'conversion', '2025-01-02', '2025-01-31', 3000000, 'completed', '2024-12-28'),
(12, 'Valentine''s Day Special', 'instagram', 'conversion', '2025-02-01', '2025-02-14', 1500000, 'completed', '2025-01-20'),
(13, 'Organic SEO Content', 'organic', 'awareness', '2023-06-01', NULL, 0, 'active', '2023-06-01'),
(14, 'Affiliate Program', 'organic', 'conversion', '2023-08-01', NULL, 0, 'active', '2023-08-01'),
(15, 'Mother''s Day Campaign', 'facebook', 'conversion', '2025-05-01', '2025-05-12', 2000000, 'active', '2025-04-15');

-- Campaign spend (daily, ~365 days worth for active campaigns)
INSERT INTO raw_marketing.campaign_spend (campaign_id, spend_date, spend_cents, impressions, clicks, conversions)
SELECT
    c.campaign_id,
    d.dt::DATE,
    GREATEST(0, (c.budget_cents / 30) + ((EXTRACT(DOY FROM d.dt)::INT * c.campaign_id * 37) % (c.budget_cents / 60)) - (c.budget_cents / 120)),
    ((EXTRACT(DOY FROM d.dt)::INT * c.campaign_id * 131) % 50000) + 5000,
    ((EXTRACT(DOY FROM d.dt)::INT * c.campaign_id * 43) % 2000) + 100,
    ((EXTRACT(DOY FROM d.dt)::INT * c.campaign_id * 17) % 50) + 1
FROM raw_marketing.campaigns c
CROSS JOIN generate_series(
    GREATEST(c.start_date, '2024-01-01'::DATE),
    LEAST(COALESCE(c.end_date, '2025-04-27'::DATE), '2025-04-27'::DATE),
    '1 day'
) AS d(dt)
WHERE c.channel NOT IN ('organic')
ON CONFLICT (campaign_id, spend_date) DO NOTHING;

-- Web sessions (~10000 sessions)
INSERT INTO raw_marketing.web_sessions (session_id, visitor_id, customer_id, session_start, session_end, landing_page, page_views, utm_source, utm_medium, utm_campaign, device_type, browser, country, converted, order_id)
SELECT
    md5(s.id::TEXT || 'session'),
    md5(((s.id * 7) % 3000)::TEXT || 'visitor'),
    CASE WHEN s.id % 3 = 0 THEN ((s.id * 7) % 200) + 1 ELSE NULL END,
    TIMESTAMP '2024-01-01' + ((s.id * 7919) % 480) * INTERVAL '1 day' + ((s.id * 127) % 1440) * INTERVAL '1 minute',
    TIMESTAMP '2024-01-01' + ((s.id * 7919) % 480) * INTERVAL '1 day' + ((s.id * 127) % 1440) * INTERVAL '1 minute' + ((s.id % 30) + 1) * INTERVAL '1 minute',
    (ARRAY['/','/products','/products/category','/deals','/about','/blog','/cart'])[((s.id * 13) % 7) + 1],
    ((s.id * 3) % 15) + 1,
    (ARRAY['google','facebook','instagram','direct','organic','tiktok','email',NULL])[((s.id * 17) % 8) + 1],
    (ARRAY['cpc','social','social','none','organic','social','email',NULL])[((s.id * 17) % 8) + 1],
    (ARRAY['summer_sale','brand_q1','insta_stories',NULL,'seo',NULL,'newsletter',NULL])[((s.id * 17) % 8) + 1],
    (ARRAY['desktop','mobile','mobile','tablet'])[((s.id * 11) % 4) + 1],
    (ARRAY['Chrome','Safari','Firefox','Edge','Samsung Internet'])[((s.id * 19) % 5) + 1],
    CASE WHEN random() < 0.85 THEN 'BR' WHEN random() < 0.5 THEN 'US' ELSE 'PT' END,
    CASE WHEN s.id % 8 = 0 THEN true ELSE false END,
    CASE WHEN s.id % 8 = 0 THEN ((s.id * 7) % 2000) + 1 ELSE NULL END
FROM generate_series(1, 10000) AS s(id);

-- Email events
INSERT INTO raw_marketing.email_events (campaign_id, customer_id, email, event_type, event_timestamp, subject_line)
SELECT
    c.campaign_id,
    ((s.id * 7) % 200) + 1,
    'customer' || (((s.id * 7) % 200) + 1) || '@example.com',
    e.event_type,
    c.start_date + ((s.id * 3) % 30) * INTERVAL '1 day' + e.offset_min * INTERVAL '1 minute',
    (ARRAY['🔥 Ofertas imperdíveis!','Novidades para você','Última chance!','Seu carrinho te espera','Desconto exclusivo'])[((s.id) % 5) + 1]
FROM raw_marketing.campaigns c
CROSS JOIN generate_series(1, 500) AS s(id)
CROSS JOIN (VALUES
    ('sent', 0),
    ('delivered', 1),
    ('opened', 60),
    ('clicked', 120)
) AS e(event_type, offset_min)
WHERE c.channel = 'email'
AND s.id <= 200
AND (e.event_type = 'sent'
     OR (e.event_type = 'delivered' AND s.id % 10 <> 0)
     OR (e.event_type = 'opened' AND s.id % 3 = 0)
     OR (e.event_type = 'clicked' AND s.id % 7 = 0));

-- ============================================================
-- Support data
-- ============================================================

-- Support agents
INSERT INTO raw_support.agents (agent_id, agent_name, team, tier, is_active, hire_date) VALUES
(1, 'Ana Costa', 'General', 'L1', true, '2022-03-15'),
(2, 'Bruno Mendes', 'General', 'L1', true, '2022-06-01'),
(3, 'Carla Ribeiro', 'Shipping', 'L1', true, '2022-09-10'),
(4, 'Daniel Freitas', 'Returns', 'L1', true, '2023-01-15'),
(5, 'Elisa Monteiro', 'Technical', 'L2', true, '2021-11-01'),
(6, 'Fábio Teixeira', 'Technical', 'L2', true, '2022-04-20'),
(7, 'Gisele Campos', 'Billing', 'L1', true, '2023-03-01'),
(8, 'Henrique Lopes', 'Escalation', 'L3', true, '2021-06-15'),
(9, 'Iara Martins', 'General', 'L1', false, '2022-01-10'),
(10, 'Jorge Nunes', 'Shipping', 'L2', true, '2022-07-01');

-- Support tickets (~800 tickets)
INSERT INTO raw_support.tickets (ticket_id, customer_id, order_id, channel, category, subcategory, priority, status, subject, assigned_agent_id, first_response_at, resolved_at, satisfaction_score, created_at, updated_at)
SELECT
    s.id,
    ((s.id * 7) % 200) + 1,
    CASE WHEN s.id % 2 = 0 THEN ((s.id * 11) % 2000) + 1 ELSE NULL END,
    (ARRAY['email','chat','chat','phone','social'])[((s.id * 13) % 5) + 1],
    (ARRAY['shipping','shipping','returns','product_issue','billing','general'])[((s.id * 17) % 6) + 1],
    (ARRAY['tracking','delay','refund_request','defective','charge_issue','info_request'])[((s.id * 17) % 6) + 1],
    (ARRAY['low','medium','medium','high','urgent'])[((s.id * 19) % 5) + 1],
    (ARRAY['resolved','resolved','resolved','closed','in_progress','open','waiting_customer'])[((s.id * 23) % 7) + 1],
    'Ticket about order #' || CASE WHEN s.id % 2 = 0 THEN ((s.id * 11) % 2000) + 1 ELSE 0 END,
    ((s.id * 3) % 10) + 1,
    TIMESTAMP '2023-09-01' + ((s.id * 7919) % 500) * INTERVAL '1 day' + ((s.id * 31) % 120 + 5) * INTERVAL '1 minute',
    CASE WHEN ((s.id * 23) % 7) + 1 <= 4
        THEN TIMESTAMP '2023-09-01' + ((s.id * 7919) % 500) * INTERVAL '1 day' + ((s.id * 31) % 120 + 5) * INTERVAL '1 minute' + ((s.id * 11) % 48 + 1) * INTERVAL '1 hour'
        ELSE NULL
    END,
    CASE WHEN ((s.id * 23) % 7) + 1 <= 4
        THEN GREATEST(1, LEAST(5, 3 + ((s.id * 7) % 5) - 2))
        ELSE NULL
    END,
    TIMESTAMP '2023-09-01' + ((s.id * 7919) % 500) * INTERVAL '1 day',
    TIMESTAMP '2023-09-01' + ((s.id * 7919) % 500) * INTERVAL '1 day' + ((s.id * 11) % 72) * INTERVAL '1 hour'
FROM generate_series(1, 800) AS s(id);

-- Ticket messages
INSERT INTO raw_support.ticket_messages (ticket_id, sender_type, sender_id, message_body, created_at)
SELECT
    t.ticket_id,
    CASE WHEN m.msg_num = 1 THEN 'customer' WHEN m.msg_num = 2 THEN 'agent' ELSE 'customer' END,
    CASE WHEN m.msg_num = 1 THEN t.customer_id WHEN m.msg_num = 2 THEN t.assigned_agent_id ELSE t.customer_id END,
    CASE
        WHEN m.msg_num = 1 THEN 'Olá, preciso de ajuda com meu pedido.'
        WHEN m.msg_num = 2 THEN 'Olá! Vou verificar seu caso agora. Um momento, por favor.'
        ELSE 'Obrigado pela ajuda!'
    END,
    t.created_at + (m.msg_num - 1) * INTERVAL '30 minutes'
FROM raw_support.tickets t
CROSS JOIN generate_series(1, 3) AS m(msg_num)
WHERE m.msg_num <= CASE WHEN t.status IN ('resolved','closed') THEN 3 ELSE 1 END;

-- ============================================================
-- Product enrichment data
-- ============================================================

-- Product attributes
INSERT INTO raw_product.product_attributes (product_id, attribute_name, attribute_value)
SELECT p.product_id, a.attr_name, a.attr_value
FROM raw_ecommerce.products p
CROSS JOIN LATERAL (VALUES
    ('color', (ARRAY['Black','White','Blue','Red','Silver','Gold','Green'])[((p.product_id * 7) % 7) + 1]),
    ('warranty_months', (ARRAY['3','6','12','24'])[((p.product_id * 11) % 4) + 1]),
    ('origin_country', (ARRAY['BR','CN','US','DE','JP','KR'])[((p.product_id * 13) % 6) + 1])
) AS a(attr_name, attr_value);

-- Price history
INSERT INTO raw_product.price_history (product_id, old_price_cents, new_price_cents, changed_at, reason)
SELECT
    p.product_id,
    p.price_cents + ((h.hist_num * p.product_id * 37) % 20000) - 10000,
    p.price_cents + CASE WHEN h.hist_num = 3 THEN 0 ELSE ((h.hist_num * p.product_id * 43) % 15000) - 7500 END,
    p.created_at + h.hist_num * INTERVAL '60 days',
    (ARRAY['promotion','cost_increase','competitive','clearance'])[((p.product_id * h.hist_num) % 4) + 1]
FROM raw_ecommerce.products p
CROSS JOIN generate_series(1, 3) AS h(hist_num)
WHERE p.product_id <= 30;

-- Suppliers
INSERT INTO raw_product.suppliers (supplier_id, supplier_name, country, lead_time_days, is_active, created_at) VALUES
(1, 'TechDistribuidora Ltda', 'BR', 5, true, '2022-01-01'),
(2, 'Shenzhen Electronics Co', 'CN', 30, true, '2022-01-15'),
(3, 'Euro Fashion Import', 'DE', 20, true, '2022-03-01'),
(4, 'São Paulo Têxtil', 'BR', 7, true, '2022-04-01'),
(5, 'Global Books Direct', 'US', 15, true, '2022-06-01'),
(6, 'Osaka Home Goods', 'JP', 25, true, '2022-07-01'),
(7, 'Seoul Sports Gear', 'KR', 22, true, '2022-09-01'),
(8, 'Amazon Marketplace BR', 'BR', 3, true, '2023-01-01');

-- Product-supplier relationships
INSERT INTO raw_product.product_suppliers (product_id, supplier_id, is_primary, supplier_sku, cost_cents)
SELECT
    p.product_id,
    CASE
        WHEN p.category_id IN (6,7,8,9) THEN ((p.product_id % 2) + 1)  -- electronics → suppliers 1,2
        WHEN p.category_id IN (10,11,12) THEN ((p.product_id % 2) + 3)  -- clothing → 3,4
        WHEN p.category_id IN (18,19,20) THEN 5                         -- books → 5
        WHEN p.category_id IN (13,14,15) THEN 6                         -- home → 6
        WHEN p.category_id IN (16,17) THEN 7                            -- sports → 7
        ELSE 8
    END,
    true,
    'SUP-' || p.sku,
    p.cost_cents
FROM raw_ecommerce.products p
ON CONFLICT DO NOTHING;

-- ============================================================
-- Useful date dimension for dbt date spine exercises
-- ============================================================
CREATE SCHEMA IF NOT EXISTS reference_data;

CREATE TABLE reference_data.date_dim (
    date_key DATE PRIMARY KEY,
    year INT NOT NULL,
    quarter INT NOT NULL,
    month INT NOT NULL,
    month_name VARCHAR(20) NOT NULL,
    week_of_year INT NOT NULL,
    day_of_week INT NOT NULL,
    day_name VARCHAR(20) NOT NULL,
    is_weekend BOOLEAN NOT NULL,
    is_holiday BOOLEAN DEFAULT false,
    fiscal_year INT,
    fiscal_quarter INT
);

INSERT INTO reference_data.date_dim (date_key, year, quarter, month, month_name, week_of_year, day_of_week, day_name, is_weekend, fiscal_year, fiscal_quarter)
SELECT
    d::DATE,
    EXTRACT(YEAR FROM d)::INT,
    EXTRACT(QUARTER FROM d)::INT,
    EXTRACT(MONTH FROM d)::INT,
    TO_CHAR(d, 'Month'),
    EXTRACT(WEEK FROM d)::INT,
    EXTRACT(DOW FROM d)::INT,
    TO_CHAR(d, 'Day'),
    EXTRACT(DOW FROM d) IN (0, 6),
    CASE WHEN EXTRACT(MONTH FROM d) >= 4 THEN EXTRACT(YEAR FROM d)::INT ELSE EXTRACT(YEAR FROM d)::INT - 1 END,
    CASE
        WHEN EXTRACT(MONTH FROM d) BETWEEN 4 AND 6 THEN 1
        WHEN EXTRACT(MONTH FROM d) BETWEEN 7 AND 9 THEN 2
        WHEN EXTRACT(MONTH FROM d) BETWEEN 10 AND 12 THEN 3
        ELSE 4
    END
FROM generate_series('2022-01-01'::DATE, '2026-12-31'::DATE, '1 day') AS d;

-- Mark Brazilian holidays
UPDATE reference_data.date_dim SET is_holiday = true
WHERE (month = 1 AND EXTRACT(DAY FROM date_key) = 1)   -- Ano Novo
   OR (month = 4 AND EXTRACT(DAY FROM date_key) = 21)   -- Tiradentes
   OR (month = 5 AND EXTRACT(DAY FROM date_key) = 1)    -- Dia do Trabalho
   OR (month = 9 AND EXTRACT(DAY FROM date_key) = 7)    -- Independência
   OR (month = 10 AND EXTRACT(DAY FROM date_key) = 12)  -- N. Sra. Aparecida
   OR (month = 11 AND EXTRACT(DAY FROM date_key) = 2)   -- Finados
   OR (month = 11 AND EXTRACT(DAY FROM date_key) = 15)  -- Proclamação da República
   OR (month = 12 AND EXTRACT(DAY FROM date_key) = 25); -- Natal

-- ============================================================
-- Summary counts (for verification)
-- ============================================================
-- SELECT 'categories' AS tbl, COUNT(*) FROM raw_ecommerce.categories
-- UNION ALL SELECT 'products', COUNT(*) FROM raw_ecommerce.products
-- UNION ALL SELECT 'customers', COUNT(*) FROM raw_ecommerce.customers
-- UNION ALL SELECT 'orders', COUNT(*) FROM raw_ecommerce.orders
-- UNION ALL SELECT 'order_items', COUNT(*) FROM raw_ecommerce.order_items
-- UNION ALL SELECT 'payments', COUNT(*) FROM raw_ecommerce.payments
-- UNION ALL SELECT 'shipping_events', COUNT(*) FROM raw_ecommerce.shipping_events
-- UNION ALL SELECT 'reviews', COUNT(*) FROM raw_ecommerce.reviews
-- UNION ALL SELECT 'inventory_snapshots', COUNT(*) FROM raw_ecommerce.inventory_snapshots
-- UNION ALL SELECT 'campaigns', COUNT(*) FROM raw_marketing.campaigns
-- UNION ALL SELECT 'campaign_spend', COUNT(*) FROM raw_marketing.campaign_spend
-- UNION ALL SELECT 'web_sessions', COUNT(*) FROM raw_marketing.web_sessions
-- UNION ALL SELECT 'email_events', COUNT(*) FROM raw_marketing.email_events
-- UNION ALL SELECT 'tickets', COUNT(*) FROM raw_support.tickets
-- UNION ALL SELECT 'agents', COUNT(*) FROM raw_support.agents
-- UNION ALL SELECT 'date_dim', COUNT(*) FROM reference_data.date_dim;
