CREATE TABLE customers (
    customer_id INTEGER PRIMARY KEY,
    name VARCHAR NOT NULL,
    segment VARCHAR NOT NULL
);

CREATE TABLE orders (
    order_id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL,
    ordered_at DATE NOT NULL,
    amount DECIMAL(12, 2) NOT NULL,
    status VARCHAR NOT NULL
);

CREATE TABLE refunds (
    refund_id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL,
    amount DECIMAL(12, 2) NOT NULL,
    refunded_at DATE NOT NULL
);

INSERT INTO customers VALUES
    (1, 'Ana', 'enterprise'),
    (2, 'Bruno', 'growth'),
    (3, 'Cora', 'enterprise');

INSERT INTO orders VALUES
    (101, 1, DATE '2026-01-05', 100.00, 'completed'),
    (102, 1, DATE '2026-01-20', 50.00, 'completed'),
    (103, 2, DATE '2026-02-03', 200.00, 'completed'),
    (104, 2, DATE '2026-02-10', 80.00, 'cancelled'),
    (105, 3, DATE '2026-03-01', 300.00, 'completed'),
    (106, 3, DATE '2026-03-15', 150.00, 'completed');

INSERT INTO refunds VALUES
    (201, 102, 10.00, DATE '2026-01-25'),
    (202, 103, 20.00, DATE '2026-02-05'),
    (203, 103, 5.00, DATE '2026-02-06');
