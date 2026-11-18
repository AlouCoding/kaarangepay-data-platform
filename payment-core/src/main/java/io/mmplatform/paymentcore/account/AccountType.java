package io.mmplatform.paymentcore.account;

/** Who owns the wallet. Only SYSTEM accounts may hold a negative balance. */
public enum AccountType {
    CUSTOMER,
    MERCHANT,
    AGENT,
    SYSTEM
}
