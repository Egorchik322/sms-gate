PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY,
    source_identifier TEXT NOT NULL UNIQUE,
    sender TEXT NOT NULL,
    received_at TEXT NOT NULL,
    text TEXT NOT NULL,
    multipart_reference TEXT,
    multipart_total INTEGER,
    multipart_sequence INTEGER,
    fingerprint TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS deliveries (
    id INTEGER PRIMARY KEY,
    message_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    channel TEXT NOT NULL CHECK (channel IN ('telegram', 'vk')),
    status TEXT NOT NULL CHECK (status IN ('pending', 'retry', 'sent', 'failed', 'configuration_error')),
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT,
    last_error TEXT,
    sent_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (message_id, channel)
);
CREATE INDEX IF NOT EXISTS deliveries_due_idx ON deliveries(channel, status, next_attempt_at);

CREATE TABLE IF NOT EXISTS bot_updates (update_id INTEGER PRIMARY KEY, processed_at TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS modem_status (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    device_available INTEGER NOT NULL DEFAULT 0,
    smsd_running INTEGER NOT NULL DEFAULT 0,
    last_contact_at TEXT,
    operator_name TEXT,
    network_code TEXT,
    radio_access_technology TEXT,
    registration_state TEXT,
    packet_registration_state TEXT,
    gprs_registration_state TEXT,
    network_lac TEXT,
    network_cid TEXT,
    gprs_state TEXT,
    packet_state TEXT,
    packet_lac TEXT,
    packet_cid TEXT,
    raw_csq INTEGER,
    radio_checked_at TEXT,
    signal_percent INTEGER,
    signal_dbm INTEGER,
    signal_bit_error_percent INTEGER,
    signal_checked_at TEXT,
    sent_count INTEGER,
    received_count INTEGER,
    failed_count INTEGER,
    sim_storage_name TEXT,
    sim_storage_used INTEGER,
    sim_storage_capacity INTEGER,
    sim_storage_free INTEGER,
    sim_storage_percent INTEGER,
    sim_storage_checked_at TEXT,
    last_received_at TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS outage_state (
    name TEXT PRIMARY KEY,
    opened_at TEXT,
    active INTEGER NOT NULL DEFAULT 0,
    recovered_at TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY,
    event_type TEXT NOT NULL,
    message_id INTEGER REFERENCES messages(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    details TEXT
);
