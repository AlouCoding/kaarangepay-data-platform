package io.mmplatform.paymentcore.transaction;

public enum TransactionStatus {
    /** Money moved; ledger entries exist. */
    COMPLETED,
    /** Business refusal (funds, blocked account); recorded for analytics, no ledger entries. */
    FAILED
}
