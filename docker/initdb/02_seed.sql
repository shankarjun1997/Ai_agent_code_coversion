-- Seed data — small but realistic. Generated with generate_series so
-- the demo has populated row counts (12K+ rows total) without bloating the image.

SET search_path TO sales, public;

-- Products
INSERT INTO sales.products (product_sku, product_name, category, list_price, cost_price)
SELECT
  'SKU-' || LPAD(g::text, 5, '0'),
  (ARRAY['Wireless Headphones','Cotton Tee','Running Shoes','Smart Watch','Yoga Mat',
         'Coffee Maker','Backpack','Sunglasses','Water Bottle','Notebook'])[1 + (g % 10)],
  (ARRAY['Electronics','Apparel','Footwear','Home','Sports'])[1 + (g % 5)],
  ROUND((10 + RANDOM()*490)::numeric, 2),
  ROUND((5  + RANDOM()*250)::numeric, 2)
FROM generate_series(1, 80) g;

-- Sales reps
INSERT INTO sales.sales_reps (full_name, email, region, hired_on)
SELECT
  (ARRAY['Alex','Bailey','Casey','Drew','Emery','Finley','Gray','Harper'])[1 + (g % 8)] || ' ' ||
  (ARRAY['Kim','Lopez','Martin','Nguyen','Ortiz','Patel','Quinn','Rivera'])[1 + (g % 8)],
  'rep' || g || '@sqlgen-demo.local',
  (ARRAY['NORTHEAST','SOUTHEAST','MIDWEST','WEST','SOUTH'])[1 + (g % 5)],
  DATE '2018-01-01' + (RANDOM() * 2500)::int
FROM generate_series(1, 20) g;

-- Customers
INSERT INTO sales.customers (
  first_name, last_name, email, phone, date_of_birth, country_code,
  loyalty_tier, lifetime_value, first_order_at, last_order_at, is_active
)
SELECT
  (ARRAY['Alex','Sam','Jordan','Taylor','Morgan','Riley','Avery','Quinn','Reese','Skylar',
         'Parker','Cameron','Hayden','Rowan','Sage','Phoenix','River','Sasha','Logan','Emerson'])[1 + (g % 20)],
  (ARRAY['Smith','Johnson','Williams','Brown','Jones','Garcia','Miller','Davis','Rodriguez','Martinez',
         'Hernandez','Lopez','Gonzalez','Wilson','Anderson','Thomas','Taylor','Moore','Jackson','Martin'])[1 + (g % 20)],
  'customer' || g || '@example.com',
  '+1-555-' || LPAD(((RANDOM()*9000)::int + 1000)::text, 4, '0') || '-' ||
              LPAD(((RANDOM()*9000)::int + 1000)::text, 4, '0'),
  DATE '1955-01-01' + (RANDOM() * 18000)::int,
  (ARRAY['US','CA','GB','DE','FR','AU','JP','IN','BR','MX'])[1 + (g % 10)],
  (ARRAY['BRONZE','BRONZE','BRONZE','SILVER','SILVER','GOLD','PLATINUM'])[1 + (g % 7)],
  ROUND((RANDOM()*8000)::numeric, 2),
  NOW() - (RANDOM() * INTERVAL '1000 days'),
  NOW() - (RANDOM() * INTERVAL '60 days'),
  RANDOM() > 0.05
FROM generate_series(1, 1500) g;

-- Orders
INSERT INTO sales.orders (customer_id, order_date, status, total_amount, currency, channel, placed_at)
SELECT
  ((RANDOM()*1499)::int + 1),
  CURRENT_DATE - (RANDOM() * 720)::int,
  (ARRAY['PLACED','SHIPPED','DELIVERED','DELIVERED','DELIVERED','CANCELLED','RETURNED'])[1 + (g % 7)],
  ROUND((20 + RANDOM()*900)::numeric, 2),
  (ARRAY['USD','USD','USD','EUR','GBP'])[1 + (g % 5)],
  (ARRAY['WEB','WEB','MOBILE','MOBILE','STORE','PHONE'])[1 + (g % 6)],
  NOW() - (RANDOM() * INTERVAL '720 days')
FROM generate_series(1, 4000) g;

-- Order items
INSERT INTO sales.order_items (order_id, product_sku, quantity, unit_price, discount_pct)
SELECT
  ((RANDOM()*3999)::int + 1),
  'SKU-' || LPAD(((RANDOM()*79)::int + 1)::text, 5, '0'),
  ((RANDOM()*5)::int + 1),
  ROUND((10 + RANDOM()*490)::numeric, 2),
  ROUND((RANDOM()*25)::numeric, 2)
FROM generate_series(1, 9000) g;

-- Audit log
INSERT INTO sales.audit_log (actor, action, target, details)
SELECT
  'user' || ((RANDOM()*49)::int + 1) || '@sqlgen-demo.local',
  (ARRAY['LOGIN','UPDATE','INSERT','DELETE','EXPORT','VIEW'])[1 + (g % 6)],
  (ARRAY['customers/4521','orders/8821','products/SKU-00041','reports/q3','dashboard'])[1 + (g % 5)],
  'demo audit entry ' || g
FROM generate_series(1, 2000) g;

-- Refresh stats so information_schema returns sensible row estimates
ANALYZE sales.customers;
ANALYZE sales.orders;
ANALYZE sales.order_items;
ANALYZE sales.products;
ANALYZE sales.sales_reps;
ANALYZE sales.audit_log;
