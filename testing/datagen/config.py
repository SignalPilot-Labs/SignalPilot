"""
Central configuration for data generation volumes and database connections.
Adjust ROW_COUNTS to scale data up/down. Default targets ~5GB total.
"""

from dataclasses import dataclass

# ── Database connection config ──────────────────────────────────────────────

ENTERPRISE_DB = {
    "host": "localhost",
    "port": 5601,
    "dbname": "enterprise_prod",
    "user": "enterprise_admin",
    "password": "Ent3rpr1se!S3cur3",
}

WAREHOUSE_DB = {
    "host": "localhost",
    "port": 5602,
    "dbname": "analytics_warehouse",
    "user": "warehouse_admin",
    "password": "W4reh0use!An4lyt1cs",
}

# ── Row counts (tuned for ~5GB total across both DBs) ──────────────────────

@dataclass
class RowCounts:
    # Enterprise OLTP
    customers: int = 2_000_000
    employees: int = 10_000
    products: int = 50_000
    orders: int = 5_000_000
    order_items: int = 15_000_000
    payments: int = 5_000_000
    support_tickets: int = 500_000
    api_keys: int = 500
    audit_log: int = 1_000_000
    internal_creds: int = 50

    # Warehouse analytics
    dim_dates_years: int = 10        # generates ~3650 rows
    dim_customers: int = 2_000_000
    dim_products: int = 50_000
    dim_employees: int = 10_000
    dim_channels: int = 25
    fact_sales: int = 10_000_000
    fact_web_events: int = 5_000_000
    fact_inventory: int = 1_000_000
    raw_customer_events: int = 3_000_000
    raw_transactions: int = 5_000_000
    ml_customer_features: int = 2_000_000
    ml_churn_predictions: int = 2_000_000


COUNTS = RowCounts()

# ── Batch sizes for COPY operations ────────────────────────────────────────

BATCH_SIZE = 50_000         # rows per CSV batch written to COPY
PROGRESS_EVERY = 250_000    # print progress every N rows

# ── Reference data ─────────────────────────────────────────────────────────

SEGMENTS = ["enterprise", "mid-market", "smb", "startup", "government", "education"]
LOYALTY_TIERS = ["bronze", "silver", "gold", "platinum", "diamond"]
DEPARTMENTS = [
    "Engineering", "Sales", "Marketing", "Finance", "HR",
    "Legal", "Operations", "Support", "Product", "Data",
    "Security", "DevOps", "Design", "QA", "Executive",
]
CATEGORIES = [
    "Electronics", "Clothing", "Home & Garden", "Sports", "Books",
    "Automotive", "Health", "Food & Beverage", "Office", "Toys",
    "Software", "Industrial", "Pet Supplies", "Beauty", "Jewelry",
]
SUBCATEGORIES = {
    "Electronics": ["Laptops", "Phones", "Tablets", "Audio", "Cameras", "Accessories"],
    "Clothing": ["Men", "Women", "Kids", "Shoes", "Accessories", "Outerwear"],
    "Home & Garden": ["Furniture", "Kitchen", "Bedding", "Tools", "Lighting", "Decor"],
    "Sports": ["Fitness", "Outdoor", "Team Sports", "Water Sports", "Winter Sports"],
    "Books": ["Fiction", "Non-Fiction", "Technical", "Children", "Academic"],
    "Software": ["SaaS", "Desktop", "Mobile", "Enterprise", "Security"],
}
BRANDS = [
    "Acme Corp", "TechFlow", "NovaStar", "Pinnacle", "Vertex",
    "BlueRidge", "IronForge", "SkyBound", "DeepRoot", "BrightEdge",
    "CoreSync", "FlexWave", "QuantumLeap", "RedLine", "SilverPeak",
]
ORDER_STATUSES = ["pending", "confirmed", "processing", "shipped", "delivered", "cancelled", "returned"]
PAYMENT_METHODS = ["credit_card", "debit_card", "bank_transfer", "paypal", "apple_pay", "crypto"]
CARD_TYPES = ["visa", "mastercard", "amex", "discover"]
TICKET_CATEGORIES = [
    "billing", "shipping", "product_defect", "account", "technical",
    "refund", "feature_request", "complaint", "general",
]
TICKET_PRIORITIES = ["low", "medium", "high", "critical"]
TICKET_STATUSES = ["open", "in_progress", "waiting_customer", "escalated", "resolved", "closed"]
CHANNELS = [
    ("Web - US", "online", "North America", "US"),
    ("Web - EU", "online", "Europe", "DE"),
    ("Web - APAC", "online", "Asia Pacific", "JP"),
    ("Mobile App", "mobile", "Global", "US"),
    ("Retail - NYC", "retail", "North America", "US"),
    ("Retail - London", "retail", "Europe", "GB"),
    ("Retail - Tokyo", "retail", "Asia Pacific", "JP"),
    ("Partner - AWS", "partner", "Global", "US"),
    ("Partner - Azure", "partner", "Global", "US"),
    ("Wholesale - NA", "wholesale", "North America", "US"),
    ("Wholesale - EU", "wholesale", "Europe", "DE"),
    ("Marketplace", "marketplace", "Global", "US"),
    ("Telemarketing", "outbound", "North America", "US"),
    ("Enterprise Direct", "direct", "Global", "US"),
]
EVENT_TYPES = [
    "page_view", "product_view", "add_to_cart", "remove_from_cart",
    "checkout_start", "checkout_complete", "search", "signup",
    "login", "logout", "wishlist_add", "review_submit",
]
DEVICE_TYPES = ["desktop", "mobile", "tablet"]
BROWSERS = ["Chrome", "Safari", "Firefox", "Edge", "Samsung Internet"]
US_STATES = [
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN","IA",
    "KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ",
    "NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VT",
    "VA","WA","WV","WI","WY",
]
REGIONS = ["North America", "Europe", "Asia Pacific", "Latin America", "Middle East"]
