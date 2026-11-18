package io.mmplatform.paymentcore.transaction;

/** Why a well-formed transaction was refused. Stored as text in {@code transactions.failure_reason}. */
public enum FailureReason {
    INSUFFICIENT_FUNDS,
    ACCOUNT_BLOCKED
}
