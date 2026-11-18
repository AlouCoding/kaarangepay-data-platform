package io.mmplatform.paymentcore.transaction;

import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import io.mmplatform.paymentcore.common.IdempotencyConflictException;
import java.time.Instant;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.stereotype.Service;

/**
 * Entry point for money movements: idempotency (ADR 0003) + metrics.
 *
 * <p>Deliberately <b>not</b> {@code @Transactional}: when two concurrent requests share a key,
 * the losing database transaction is rolled back, and the replay lookup must run in a fresh one.
 */
@Service
public class TransactionFacade {

    private final TransactionService service;
    private final TransactionRepository transactions;
    private final MeterRegistry meters;

    public TransactionFacade(TransactionService service, TransactionRepository transactions, MeterRegistry meters) {
        this.service = service;
        this.transactions = transactions;
        this.meters = meters;
    }

    public Outcome submit(String idempotencyKey, TransactionCommand command, Instant occurredAt) {
        Timer.Sample sample = Timer.start(meters);
        String hash = command.requestHash();

        Outcome outcome = transactions.findByIdempotencyKey(idempotencyKey)
                .map(existing -> replay(idempotencyKey, existing, hash))
                .orElseGet(() -> executeOrReplay(idempotencyKey, hash, command, occurredAt));

        String[] tags = {
                "type", outcome.transaction().getType().name(),
                "status", outcome.transaction().getStatus().name(),
                "replay", Boolean.toString(outcome.replayed())};
        meters.counter("mm.transactions", tags).increment();
        sample.stop(meters.timer("mm.transactions.latency", tags));
        return outcome;
    }

    private Outcome executeOrReplay(String key, String hash, TransactionCommand command, Instant occurredAt) {
        try {
            return new Outcome(service.execute(key, hash, command, occurredAt), false);
        } catch (DataIntegrityViolationException e) {
            // A concurrent request with the same key committed first: replay its result.
            return transactions.findByIdempotencyKey(key)
                    .map(existing -> replay(key, existing, hash))
                    .orElseThrow(() -> e);
        }
    }

    private static Outcome replay(String key, Transaction existing, String hash) {
        if (!existing.getRequestHash().equals(hash)) {
            throw new IdempotencyConflictException(key);
        }
        return new Outcome(existing, true);
    }

    /** @param replayed true if the result comes from an earlier request with the same key */
    public record Outcome(Transaction transaction, boolean replayed) {}
}
