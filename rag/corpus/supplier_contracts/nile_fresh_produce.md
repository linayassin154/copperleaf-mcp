# Supplier Contract — Nile Fresh Produce

Supplier ID: 1 | Contact: orders@nilefresh.com | Category: Produce

## Section 1 — Delivery Terms

### 1.1 Delivery Window
Deliveries are scheduled for confirmation within 3 business days of order
placement, with an expected delivery date set at order time (see
`supplier_orders.expected_delivery` in the operational database).

### 1.2 Late Delivery Definition
A delivery is considered late if it arrives more than 24 hours after the
confirmed `expected_delivery` date. Three late deliveries within any
rolling 90-day window trigger a mandatory account review under Section 3.2.

## Section 2 — Quality Guarantee

### 2.1 Freshness Standard
All produce must be harvested within 5 days of the delivery date. Nile
Fresh Produce warrants that produce will remain usable for the shelf-life
windows specified in the Food Safety & Storage Policy (Section 3), provided
Copperleaf stores it correctly on arrival.

### 2.2 Damaged Goods on Arrival
If more than 10% of a delivered quantity is visibly damaged or spoiled on
arrival, the entire line item may be rejected at no cost, and a replacement
delivery must be dispatched within 48 hours.

## Section 3 — Return & Remediation Policy

### 3.1 Standard Return Window
Damaged-in-delivery claims must be filed within 24 hours of receiving. Claims
filed after this window are not eligible for credit or replacement.

### 3.2 Late Delivery Remediation
Per Section 1.2, three late deliveries in a rolling 90-day window trigger a
mandatory account review. Copperleaf may request a service credit equal to
5% of the affected order's value per late delivery beyond the second
occurrence in that window.

### 3.3 Repeated Quality Failures
If damaged-in-delivery claims are filed against three or more separate
orders within any rolling 60-day window, Copperleaf may invoke a 30-day
supplier probation period during which order volume is capped at 50% of the
trailing 90-day average, pending a quality review meeting.

## Section 4 — Contact & Escalation

### 4.1 Standard Contact
orders@nilefresh.com for routine ordering; account issues should reference
the branch ID and affected `order_id` from `supplier_orders`.

### 4.2 Escalation Path
Repeated late deliveries or quality failures (Sections 3.2, 3.3) should be
escalated in writing, citing the specific order IDs and dates involved, to
trigger the contractual remediation clauses above rather than relying on
informal follow-up.