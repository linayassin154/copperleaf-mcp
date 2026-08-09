# Copperleaf Kitchens — Food Safety & Storage Policy

This document governs storage, handling, and shelf-life practices across all
Copperleaf Kitchens branches. It exists because storage requirements differ
by category and are not captured anywhere in the inventory database — staff
have historically relied on memory or asking a manager.

## Section 1 — Storage Temperature Requirements

### 1.1 Produce (tomatoes, onions, cucumbers, and similar)
Store at 4-7°C in ventilated crates. Do not store produce in sealed
containers — trapped moisture accelerates spoilage. Roma tomatoes
specifically should not be refrigerated below 4°C, as cold storage below
this point degrades texture and flavor without extending shelf life.

### 1.2 Dairy (milk, feta cheese, and similar)
Store at or below 4°C at all times. Milk left above 4°C for more than 2
cumulative hours must be discarded regardless of its printed expiry date.
Feta cheese stored in brine has a materially longer shelf life than
vacuum-packed feta — check the supplier packaging type before applying a
standard shelf-life assumption.

### 1.3 Protein (chicken, salmon, ribeye, and similar)
Store at or below 0-2°C. Raw poultry must be stored on the lowest shelf of
any shared refrigeration unit to prevent drip contamination onto
ready-to-eat items. Seafood (e.g., salmon fillet) should be used within 48
hours of delivery regardless of printed use-by date, due to faster bacterial
growth in fish tissue compared to red meat or poultry.

### 1.4 Dry goods (rice and similar)
Store in a cool, dry area below 25°C, in sealed containers to prevent pest
contamination. Shelf life is long (12+ months) provided moisture exposure is
avoided.

## Section 2 — Receiving & Delivery Inspection

### 2.1 Temperature check on arrival
Any delivered item outside its required storage temperature range (Section
1) on arrival must be logged as `damaged_in_delivery` if used for a
write-off, even if the item looks visually acceptable. Temperature
excursions are not always visible.

### 2.2 Visual inspection
Produce and protein deliveries must be visually inspected for damage,
discoloration, or off-odor before shelving. Items failing inspection should
never be shelved "to make quota" for later inventory reconciliation — reject
at the door and note it against the relevant supplier order.

## Section 3 — Shelf-Life Guidance by Category

| Category | Typical shelf life once received | Notes |
|---|---|---|
| Produce | 3-7 days | Highly variable; tomatoes and cucumbers are faster to spoil than onions |
| Dairy | 5-10 days after opening | Milk shorter than hard cheese; feta depends on brine (see 1.2) |
| Protein | 1-3 days (seafood), 2-4 days (poultry/red meat) | Seafood is the fastest-spoiling category in this list |
| Dry goods | Months | Primary risk is pest/moisture, not spoilage |

## Section 4 — Write-Off Reason Guidance

This section exists to help a manager or assistant pick the correct write-off
`reason` code (see the waste policy resource for the full list) based on what
actually happened, since the wrong code corrupts pattern-detection over time.

### 4.1 `spoiled_before_use`
Use when an item passed inspection at receiving, was stored correctly per
Section 1, and still spoiled before it could be used — i.e., normal shelf-life
was exceeded during ordinary kitchen operations.

### 4.2 `damaged_in_delivery`
Use when the item failed inspection at receiving (Section 2.1 or 2.2), or
when it can be established the item was already compromised before it
reached branch storage. Do not use this code for spoilage that occurred
after correct receiving and storage — that is `spoiled_before_use` or
`prep_error` depending on cause.

### 4.3 `prep_error`
Use when the loss resulted from a kitchen handling mistake (e.g., left out
of refrigeration during prep, cross-contaminated, incorrectly portioned and
discarded) rather than a storage or delivery failure.

## Section 5 — Why This Matters

A write-off reason code that doesn't reflect what actually happened hides
the real pattern from managers — a `spoiled_before_use` code applied to
what was actually a delivery problem makes a systemic supplier issue
invisible until it has already cost significant money.