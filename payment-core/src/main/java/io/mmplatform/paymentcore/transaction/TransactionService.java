package io.mmplatform.paymentcore.transaction;

import io.mmplatform.paymentcore.account.Account;
import io.mmplatform.paymentcore.account.AccountRepository;
import io.mmplatform.paymentcore.common.InvalidRequestException;
import io.mmplatform.paymentcore.common.NotFoundException;
import io.mmplatform.paymentcore.config.PlatformProperties;
import io.mmplatform.paymentcore.ledger.EntryDirection;
import io.mmplatform.paymentcore.ledger.LedgerEntry;
import io.mmplatform.paymentcore.ledger.LedgerEntryRepository;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.function.Function;
import java.util.stream.Collectors;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * Executes one money movement as a single ACID database transaction.
 *
 * <p>Steps: compute fee → lock the involved accounts in id order → validate routing →
 * check status and funds → write the transaction row → post balanced ledger entries.
 * Idempotency is handled one level up, in {@link TransactionFacade}.
 */
@Service
public class TransactionService {

    private final AccountRepository accounts;
    private final TransactionRepository transactions;
    private final LedgerEntryRepository entries;
    private final FeePolicy feePolicy;
    private final TransactionClock clock;
    private final UUID treasuryId;
    private final UUID feesId;

    public TransactionService(AccountRepository accounts, TransactionRepository transactions,
                              LedgerEntryRepository entries, FeePolicy feePolicy,
                              TransactionClock clock, PlatformProperties properties) {
        this.accounts = accounts;
        this.transactions = transactions;
        this.entries = entries;
        this.feePolicy = feePolicy;
        this.clock = clock;
        this.treasuryId = properties.systemAccounts().treasuryId();
        this.feesId = properties.systemAccounts().feesId();
    }

    @Transactional
    public Transaction execute(String idempotencyKey, String requestHash,
                               TransactionCommand command, Instant occurredAt) {
        if (command.sourceAccountId().equals(command.destinationAccountId())) {
            throw new InvalidRequestException("Source and destination accounts must differ");
        }
        long fee = feePolicy.feeFor(command.type(), command.amount());

        // 1. Lock every account whose balance may change, in a global order (no deadlocks).
        Set<UUID> ids = new HashSet<>(List.of(command.sourceAccountId(), command.destinationAccountId()));
        if (fee > 0) {
            ids.add(feesId);
        }
        Map<UUID, Account> locked = accounts.lockAllByIdIn(ids).stream()
                .collect(Collectors.toMap(Account::getId, Function.identity()));
        Account source = require(locked, command.sourceAccountId());
        Account destination = require(locked, command.destinationAccountId());

        // 2. Client errors: rejected, nothing recorded.
        validateRouting(command, source, destination);

        Instant recordedAt = clock.processingTime();

        // 3. Business refusals: recorded as FAILED (useful data), no money moves.
        FailureReason refusal = null;
        if (!source.isActive() || !destination.isActive()) {
            refusal = FailureReason.ACCOUNT_BLOCKED;
        } else if (!source.canPay(Math.addExact(command.amount(), fee))) {
            refusal = FailureReason.INSUFFICIENT_FUNDS;
        }
        if (refusal != null) {
            return transactions.saveAndFlush(Transaction.failed(
                    idempotencyKey, requestHash, command, fee, refusal, occurredAt, recordedAt));
        }

        // 4. Persist the transaction first: a duplicate idempotency key fails here, before any entry.
        Transaction tx = transactions.saveAndFlush(Transaction.completed(
                idempotencyKey, requestHash, command, fee, occurredAt, recordedAt));

        // 5. Post balanced entries: debit = amount + fee ; credits = amount (+ fee).
        List<LedgerEntry> lines = new ArrayList<>(3);
        lines.add(entry(tx, source, EntryDirection.DEBIT, tx.totalDebit(),
                source.debit(tx.totalDebit(), recordedAt), recordedAt));
        lines.add(entry(tx, destination, EntryDirection.CREDIT, tx.getAmount(),
                destination.credit(tx.getAmount(), recordedAt), recordedAt));
        if (fee > 0) {
            Account fees = require(locked, feesId);
            lines.add(entry(tx, fees, EntryDirection.CREDIT, fee, fees.credit(fee, recordedAt), recordedAt));
        }
        entries.saveAll(lines);
        return tx;
    }

    private void validateRouting(TransactionCommand command, Account source, Account destination) {
        if (!command.type().allows(source.getType(), destination.getType())) {
            throw new InvalidRequestException("%s is not allowed from %s to %s".formatted(
                    command.type(), source.getType(), destination.getType()));
        }
        // Among system accounts, only the treasury can issue e-money.
        if (command.type() == TransactionType.FLOAT_TOPUP && !source.getId().equals(treasuryId)) {
            throw new InvalidRequestException("FLOAT_TOPUP must come from the treasury account");
        }
    }

    private static Account require(Map<UUID, Account> locked, UUID id) {
        Account account = locked.get(id);
        if (account == null) {
            throw new NotFoundException("Account", id);
        }
        return account;
    }

    private static LedgerEntry entry(Transaction tx, Account account, EntryDirection direction,
                                     long amount, long balanceAfter, Instant recordedAt) {
        return new LedgerEntry(tx.getId(), account.getId(), direction, amount, balanceAfter,
                tx.getOccurredAt(), recordedAt);
    }
}
