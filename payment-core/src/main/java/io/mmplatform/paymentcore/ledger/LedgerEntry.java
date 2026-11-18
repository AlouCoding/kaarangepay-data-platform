package io.mmplatform.paymentcore.ledger;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.Instant;
import java.util.UUID;

/** One immutable line of the double-entry ledger. Never updated, never deleted. */
@Entity
@Table(name = "ledger_entries")
public class LedgerEntry {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "transaction_id", nullable = false, updatable = false)
    private UUID transactionId;

    @Column(name = "account_id", nullable = false, updatable = false)
    private UUID accountId;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, updatable = false, length = 6)
    private EntryDirection direction;

    @Column(nullable = false, updatable = false)
    private long amount;

    @Column(name = "balance_after", nullable = false, updatable = false)
    private long balanceAfter;

    @Column(name = "occurred_at", nullable = false, updatable = false)
    private Instant occurredAt;

    @Column(name = "recorded_at", nullable = false, updatable = false)
    private Instant recordedAt;

    /** Required by JPA. */
    protected LedgerEntry() {}

    public LedgerEntry(UUID transactionId, UUID accountId, EntryDirection direction, long amount,
                       long balanceAfter, Instant occurredAt, Instant recordedAt) {
        if (amount <= 0) {
            throw new IllegalArgumentException("Entry amount must be positive");
        }
        this.transactionId = transactionId;
        this.accountId = accountId;
        this.direction = direction;
        this.amount = amount;
        this.balanceAfter = balanceAfter;
        this.occurredAt = occurredAt;
        this.recordedAt = recordedAt;
    }

    /** Signed effect on the account balance: +amount for CREDIT, −amount for DEBIT. */
    public long signedAmount() {
        return direction == EntryDirection.CREDIT ? amount : -amount;
    }

    public Long getId() { return id; }
    public UUID getTransactionId() { return transactionId; }
    public UUID getAccountId() { return accountId; }
    public EntryDirection getDirection() { return direction; }
    public long getAmount() { return amount; }
    public long getBalanceAfter() { return balanceAfter; }
    public Instant getOccurredAt() { return occurredAt; }
    public Instant getRecordedAt() { return recordedAt; }
}
