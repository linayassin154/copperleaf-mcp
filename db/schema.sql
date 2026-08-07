-- Copperleaf Kitchens Inventory Database
-- SQLite

PRAGMA foreign_keys = ON;

CREATE TABLE branches (
    branch_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    address         TEXT NOT NULL,
    phone           TEXT
);

CREATE TABLE staff (
    staff_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    branch_id       INTEGER NOT NULL,
    full_name       TEXT NOT NULL,
    email           TEXT NOT NULL UNIQUE,
    role            TEXT NOT NULL CHECK (role IN ('staff', 'manager')),
    active          INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    api_token       TEXT NOT NULL UNIQUE,
    FOREIGN KEY (branch_id) REFERENCES branches(branch_id)
);

CREATE TABLE suppliers (
    supplier_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    contact_email   TEXT,
    phone           TEXT
);

CREATE TABLE inventory_items (
    item_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    branch_id           INTEGER NOT NULL,
    supplier_id         INTEGER,
    name                TEXT NOT NULL,
    category            TEXT NOT NULL CHECK (category IN ('produce', 'protein', 'dairy', 'dry_goods', 'beverage', 'other')),
    unit                TEXT NOT NULL CHECK (unit IN ('kg', 'g', 'l', 'ml', 'unit', 'case')),
    current_quantity    REAL NOT NULL DEFAULT 0 CHECK (current_quantity >= 0),
    reorder_threshold   REAL NOT NULL DEFAULT 0,
    unit_cost           REAL NOT NULL DEFAULT 0,
    FOREIGN KEY (branch_id) REFERENCES branches(branch_id),
    FOREIGN KEY (supplier_id) REFERENCES suppliers(supplier_id)
);

CREATE TABLE inventory_transactions (
    transaction_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id             INTEGER NOT NULL,
    staff_id            INTEGER NOT NULL,
    change_type         TEXT NOT NULL CHECK (change_type IN ('restock', 'write_off', 'usage', 'adjustment')),
    quantity_change      REAL NOT NULL,
    reason              TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (item_id) REFERENCES inventory_items(item_id),
    FOREIGN KEY (staff_id) REFERENCES staff(staff_id),
    CHECK (
        (change_type = 'restock'   AND quantity_change > 0) OR
        (change_type = 'write_off' AND quantity_change < 0) OR
        (change_type = 'usage'     AND quantity_change < 0) OR
        (change_type = 'adjustment' AND quantity_change != 0)
    )
);

CREATE TABLE supplier_orders (
    order_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    branch_id           INTEGER NOT NULL,
    supplier_id         INTEGER NOT NULL,
    item_id             INTEGER NOT NULL,
    quantity            REAL NOT NULL CHECK (quantity > 0),
    status              TEXT NOT NULL CHECK (status IN ('pending', 'delivered', 'cancelled')) DEFAULT 'pending',
    ordered_at          TEXT NOT NULL DEFAULT (datetime('now')),
    expected_delivery   TEXT,
    FOREIGN KEY (branch_id) REFERENCES branches(branch_id),
    FOREIGN KEY (supplier_id) REFERENCES suppliers(supplier_id),
    FOREIGN KEY (item_id) REFERENCES inventory_items(item_id)
);

CREATE INDEX idx_items_branch ON inventory_items(branch_id);
CREATE INDEX idx_txn_item ON inventory_transactions(item_id);
CREATE INDEX idx_txn_created ON inventory_transactions(created_at);
CREATE INDEX idx_orders_branch_status ON supplier_orders(branch_id, status);

CREATE TRIGGER trg_supplier_orders_branch_match_insert
BEFORE INSERT ON supplier_orders
FOR EACH ROW
WHEN (
    SELECT branch_id FROM inventory_items WHERE item_id = NEW.item_id
) != NEW.branch_id
BEGIN
    SELECT RAISE(ABORT, 'supplier_orders.branch_id must match inventory_items.branch_id for item_id');
END;

CREATE TRIGGER trg_supplier_orders_branch_match_update
BEFORE UPDATE ON supplier_orders
FOR EACH ROW
WHEN (
    SELECT branch_id FROM inventory_items WHERE item_id = NEW.item_id
) != NEW.branch_id
BEGIN
    SELECT RAISE(ABORT, 'supplier_orders.branch_id must match inventory_items.branch_id for item_id');
END;
