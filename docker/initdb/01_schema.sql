-- Demo CRM/Sales Postgres database for SQLGen stakeholder demo.
-- Schema represents a typical retail source system that needs to be
-- migrated to BigQuery via Agent 2's mapping flow.

CREATE SCHEMA IF NOT EXISTS sales;
SET search_path TO sales, public;

CREATE TABLE sales.customers (
    customer_id      BIGSERIAL PRIMARY KEY,
    first_name       VARCHAR(50)  NOT NULL,
    last_name        VARCHAR(50)  NOT NULL,
    email            VARCHAR(120) NOT NULL UNIQUE,
    phone            VARCHAR(30),
    date_of_birth    DATE,
    country_code     CHAR(2)      NOT NULL,
    loyalty_tier     VARCHAR(20)  NOT NULL DEFAULT 'BRONZE',
    lifetime_value   NUMERIC(12,2) NOT NULL DEFAULT 0,
    first_order_at   TIMESTAMPTZ,
    last_order_at    TIMESTAMPTZ,
    is_active        BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE  sales.customers IS 'Master customer records for the retail program.';
COMMENT ON COLUMN sales.customers.customer_id    IS 'Surrogate primary key.';
COMMENT ON COLUMN sales.customers.first_name     IS 'Customer given name.';
COMMENT ON COLUMN sales.customers.last_name      IS 'Customer family name.';
COMMENT ON COLUMN sales.customers.email          IS 'Primary email contact (PII).';
COMMENT ON COLUMN sales.customers.phone          IS 'Mobile number, E.164 format (PII).';
COMMENT ON COLUMN sales.customers.date_of_birth  IS 'Date of birth (PII, restricted).';
COMMENT ON COLUMN sales.customers.country_code   IS 'ISO 3166-1 alpha-2 country code.';
COMMENT ON COLUMN sales.customers.loyalty_tier   IS 'BRONZE, SILVER, GOLD, PLATINUM.';
COMMENT ON COLUMN sales.customers.lifetime_value IS 'Sum of net revenue (USD).';

CREATE TABLE sales.products (
    product_sku   VARCHAR(40)  PRIMARY KEY,
    product_name  VARCHAR(120) NOT NULL,
    category      VARCHAR(40)  NOT NULL,
    list_price    NUMERIC(10,2) NOT NULL,
    cost_price    NUMERIC(10,2) NOT NULL,
    is_active     BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE sales.products IS 'Catalog of items sold.';

CREATE TABLE sales.orders (
    order_id      BIGSERIAL PRIMARY KEY,
    customer_id   BIGINT      NOT NULL REFERENCES sales.customers(customer_id),
    order_date    DATE        NOT NULL,
    status        VARCHAR(20) NOT NULL,
    total_amount  NUMERIC(12,2) NOT NULL,
    currency      CHAR(3)     NOT NULL DEFAULT 'USD',
    channel       VARCHAR(20) NOT NULL,
    placed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE  sales.orders          IS 'One row per order placed.';
COMMENT ON COLUMN sales.orders.status   IS 'PLACED, SHIPPED, DELIVERED, CANCELLED, RETURNED.';
COMMENT ON COLUMN sales.orders.channel  IS 'WEB, MOBILE, STORE, PHONE.';

CREATE TABLE sales.order_items (
    item_id      BIGSERIAL PRIMARY KEY,
    order_id     BIGINT NOT NULL REFERENCES sales.orders(order_id),
    product_sku  VARCHAR(40) NOT NULL REFERENCES sales.products(product_sku),
    quantity     INTEGER     NOT NULL,
    unit_price   NUMERIC(10,2) NOT NULL,
    discount_pct NUMERIC(5,2)  NOT NULL DEFAULT 0
);
COMMENT ON TABLE sales.order_items IS 'Line items, one row per (order, product).';

CREATE TABLE sales.sales_reps (
    rep_id     BIGSERIAL PRIMARY KEY,
    full_name  VARCHAR(120) NOT NULL,
    email      VARCHAR(120) NOT NULL UNIQUE,
    region     VARCHAR(40)  NOT NULL,
    hired_on   DATE         NOT NULL
);
COMMENT ON TABLE sales.sales_reps IS 'Internal sales representative directory.';

CREATE TABLE sales.audit_log (
    log_id      BIGSERIAL PRIMARY KEY,
    event_time  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    actor       VARCHAR(80) NOT NULL,
    action      VARCHAR(40) NOT NULL,
    target      VARCHAR(120) NOT NULL,
    details     TEXT
);
COMMENT ON TABLE sales.audit_log IS 'Append-only event log for compliance.';

CREATE INDEX idx_orders_customer ON sales.orders(customer_id);
CREATE INDEX idx_order_items_order ON sales.order_items(order_id);
