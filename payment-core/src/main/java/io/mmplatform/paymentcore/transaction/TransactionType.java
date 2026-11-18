package io.mmplatform.paymentcore.transaction;

import static io.mmplatform.paymentcore.account.AccountType.AGENT;
import static io.mmplatform.paymentcore.account.AccountType.CUSTOMER;
import static io.mmplatform.paymentcore.account.AccountType.MERCHANT;
import static io.mmplatform.paymentcore.account.AccountType.SYSTEM;

import io.mmplatform.paymentcore.account.AccountType;
import java.util.EnumSet;
import java.util.Set;

/**
 * The money movements supported by the platform, with the account types allowed
 * on each side. Names follow the PaySim vocabulary so the data can be compared
 * with that public dataset.
 */
public enum TransactionType {

    /** Treasury issues e-money to an agent (the agent deposited cash at the bank). */
    FLOAT_TOPUP(EnumSet.of(SYSTEM), EnumSet.of(AGENT)),
    /** A customer gives cash to an agent and receives e-money. */
    CASH_IN(EnumSet.of(AGENT), EnumSet.of(CUSTOMER)),
    /** A customer withdraws cash at an agent, or a merchant withdraws their takings. Fee applies. */
    CASH_OUT(EnumSet.of(CUSTOMER, MERCHANT), EnumSet.of(AGENT)),
    /** Person-to-person transfer. Fee applies. */
    TRANSFER(EnumSet.of(CUSTOMER), EnumSet.of(CUSTOMER)),
    /** A customer pays a merchant. Free for the customer. */
    PAYMENT(EnumSet.of(CUSTOMER), EnumSet.of(MERCHANT));

    private final Set<AccountType> allowedSources;
    private final Set<AccountType> allowedDestinations;

    TransactionType(Set<AccountType> allowedSources, Set<AccountType> allowedDestinations) {
        this.allowedSources = allowedSources;
        this.allowedDestinations = allowedDestinations;
    }

    public boolean allows(AccountType source, AccountType destination) {
        return allowedSources.contains(source) && allowedDestinations.contains(destination);
    }
}
