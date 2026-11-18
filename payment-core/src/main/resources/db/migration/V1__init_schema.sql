-- =====================================================================
-- V1 — Core schema of the mobile money platform.
--
-- Design principles (see docs/adr):
--   * Amounts are BIGINT in XOF minor units (XOF has no decimals).
--   * Double-entry ledger: every transaction posts entries whose debits
--     equal its credits; the sum of ALL balances is always 0 because the
--     TREASURY system account mirrors the e-money issued.
--   * Event time (occurred_at) is distinct from processing time
--     (recorded_at) — this matters for the streaming layer (phase 3).
-- =====================================================================

CREATE TABLE accounts (
    id            UUID         PRIMARY KEY,
    phone         VARCHAR(20)  NOT NULL UNIQUE,
    owner_name    VARCHAR(120) NOT NULL,
    account_type  VARCHAR(16)  NOT NULL
        CHECK (account_type IN ('CUSTOMER', 'MERCHANT', 'AGENT', 'SYSTEM')),
    status        VARCHAR(16)  NOT NULL DEFAULT 'ACTIVE'
        CHECK (status IN ('ACTIVE', 'BLOCKED')),
    currency      VARCHAR(3)    NOT NULL DEFAULT 'XOF',
    balance       BIGINT       NOT NULL DEFAULT 0,
    version       BIGINT       NOT NULL DEFAULT 0,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    -- Only system accounts (TREASURY) may go negative.
    CONSTRAINT chk_non_negative_balance
        CHECK (account_type = 'SYSTEM' OR balance >= 0)
);

CREATE TABLE transactions (
    id                      UUID         PRIMARY KEY,
    idempotency_key         VARCHAR(64)  NOT NULL UNIQUE,
    request_hash            VARCHAR(64)  NOT NULL,
    transaction_type        VARCHAR(16)  NOT NULL
        CHECK (transaction_type IN ('FLOAT_TOPUP', 'CASH_IN', 'CASH_OUT', 'TRANSFER', 'PAYMENT')),
    status                  VARCHAR(16)  NOT NULL
        CHECK (status IN ('COMPLETED', 'FAILED')),
    source_account_id       UUID         NOT NULL REFERENCES accounts (id),
    destination_account_id  UUID         NOT NULL REFERENCES accounts (id),
    amount                  BIGINT       NOT NULL CHECK (amount > 0),
    fee                     BIGINT       NOT NULL DEFAULT 0 CHECK (fee >= 0),
    currency                VARCHAR(3)    NOT NULL DEFAULT 'XOF',
    failure_reason          VARCHAR(64),
    occurred_at             TIMESTAMPTZ  NOT NULL,
    recorded_at             TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT chk_distinct_accounts CHECK (source_account_id <> destination_account_id),
    CONSTRAINT chk_failure_reason
        CHECK ((status = 'FAILED') = (failure_reason IS NOT NULL))
);

CREATE INDEX idx_transactions_source      ON transactions (source_account_id, occurred_at);
CREATE INDEX idx_transactions_destination ON transactions (destination_account_id, occurred_at);
CREATE INDEX idx_transactions_occurred_at ON transactions (occurred_at);

CREATE TABLE ledger_entries (
    id              BIGSERIAL    PRIMARY KEY,
    transaction_id  UUID         NOT NULL REFERENCES transactions (id),
    account_id      UUID         NOT NULL REFERENCES accounts (id),
    -- Wallet perspective: DEBIT = money leaves the account, CREDIT = money enters.
    direction       VARCHAR(6)   NOT NULL CHECK (direction IN ('DEBIT', 'CREDIT')),
    amount          BIGINT       NOT NULL CHECK (amount > 0),
    balance_after   BIGINT       NOT NULL,
    occurred_at     TIMESTAMPTZ  NOT NULL,
    recorded_at     TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX idx_ledger_entries_account     ON ledger_entries (account_id, id);
CREATE INDEX idx_ledger_entries_transaction ON ledger_entries (transaction_id);

-- System accounts with fixed ids (referenced by the application config).
INSERT INTO accounts (id, phone, owner_name, account_type) VALUES
    ('00000000-0000-0000-0000-000000000001', 'SYS-TREASURY', 'Platform treasury (e-money issued)', 'SYSTEM'),
    ('00000000-0000-0000-0000-000000000002', 'SYS-FEES',     'Platform fee revenue',               'SYSTEM');
