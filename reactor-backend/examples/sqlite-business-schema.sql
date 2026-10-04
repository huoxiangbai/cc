-- New isolated sample only. DECIMAL_TEXT retains exact decimal source values.
CREATE TABLE sales(category TEXT, amount DECIMAL_TEXT, occurred_at DATE);
INSERT INTO sales VALUES ('A','10.0000','2026-10-03'),('A','20.0000','2026-10-03'),('B','7.5000','2026-10-03');
