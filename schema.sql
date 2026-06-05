-- MATRIX photo archive catalog (SQLite 3)
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS lineage_groups (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    roll_number     TEXT NOT NULL,
    frame_number    TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (roll_number, frame_number)
);

CREATE TABLE IF NOT EXISTS duplicate_groups (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    group_type      TEXT NOT NULL CHECK (group_type IN ('EXACT', 'VISUAL', 'DERIVATIVE', 'LINEAGE')),
    master_asset_id INTEGER,
    confidence      REAL NOT NULL DEFAULT 0.0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (master_asset_id) REFERENCES assets(id)
);

CREATE TABLE IF NOT EXISTS assets (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    path                TEXT NOT NULL UNIQUE,
    filename            TEXT NOT NULL,
    sha256              TEXT,
    phash               TEXT,
    file_type           TEXT NOT NULL CHECK (file_type IN (
        'RAW', 'TIFF', 'JPEG', 'PSD', 'DNG', 'MP4', 'HEIC', 'OTHER'
    )),
    mime_type           TEXT,
    size_bytes          INTEGER NOT NULL DEFAULT 0,
    width               INTEGER,
    height              INTEGER,
    mtime               REAL NOT NULL,
    parent_id           INTEGER,
    xmp_sidecar_path    TEXT,
    duplicate_group_id  INTEGER,
    lineage_group_id    INTEGER,
    review_status       TEXT NOT NULL DEFAULT 'PENDING' CHECK (review_status IN (
        'PENDING', 'APPROVED', 'REJECTED', 'SKIPPED'
    )),
    confidence          REAL,
    is_master           INTEGER NOT NULL DEFAULT 0,
    roll_number         TEXT,
    frame_number        TEXT,
    lab                 TEXT,
    scanner             TEXT,
    lineage_role        TEXT CHECK (lineage_role IN (
        NULL, 'NEGATIVE', 'LAB_SCAN', 'CAMERA_SCAN', 'DNG', 'EXPORT', 'OTHER'
    )),
    scanned_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (parent_id) REFERENCES assets(id),
    FOREIGN KEY (duplicate_group_id) REFERENCES duplicate_groups(id),
    FOREIGN KEY (lineage_group_id) REFERENCES lineage_groups(id)
);

CREATE TABLE IF NOT EXISTS review_decisions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    duplicate_group_id  INTEGER NOT NULL,
    action              TEXT NOT NULL CHECK (action IN (
        'KEEP_ALL', 'DELETE_DUPLICATES', 'SKIP', 'MANUAL'
    )),
    decided_at          TEXT NOT NULL DEFAULT (datetime('now')),
    dry_run             INTEGER NOT NULL DEFAULT 1,
    notes               TEXT,
    FOREIGN KEY (duplicate_group_id) REFERENCES duplicate_groups(id)
);

CREATE TABLE IF NOT EXISTS quarantine_moves (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id        INTEGER NOT NULL,
    source_path     TEXT NOT NULL,
    quarantine_path TEXT NOT NULL,
    moved_at        TEXT NOT NULL DEFAULT (datetime('now')),
    review_decision_id INTEGER,
    FOREIGN KEY (asset_id) REFERENCES assets(id),
    FOREIGN KEY (review_decision_id) REFERENCES review_decisions(id)
);

CREATE INDEX IF NOT EXISTS idx_assets_sha256 ON assets(sha256);
CREATE INDEX IF NOT EXISTS idx_assets_phash ON assets(phash);
CREATE INDEX IF NOT EXISTS idx_assets_duplicate_group ON assets(duplicate_group_id);
CREATE INDEX IF NOT EXISTS idx_assets_lineage_group ON assets(lineage_group_id);
CREATE INDEX IF NOT EXISTS idx_assets_parent ON assets(parent_id);
CREATE INDEX IF NOT EXISTS idx_assets_review ON assets(review_status);