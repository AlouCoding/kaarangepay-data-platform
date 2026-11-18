package io.mmplatform.paymentcore.transaction;

import io.mmplatform.paymentcore.common.NotFoundException;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;
import jakarta.validation.constraints.Size;
import java.net.URI;
import java.time.Instant;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * Money movement API.
 *
 * <ul>
 *   <li>201 — completed (first time)</li>
 *   <li>200 — completed, replayed from an earlier request with the same key</li>
 *   <li>422 — refused (insufficient funds, blocked account) or invalid routing</li>
 *   <li>409 — idempotency key reused with a different payload</li>
 * </ul>
 * Header {@code Idempotent-Replay: true|false} tells the client which case applies.
 */
@RestController
@RequestMapping("/api/v1/transactions")
public class TransactionController {

    static final String IDEMPOTENCY_KEY = "Idempotency-Key";
    static final String SIMULATED_TIME = "X-Simulated-Time";
    static final String REPLAY_HEADER = "Idempotent-Replay";

    private final TransactionFacade facade;
    private final TransactionRepository transactions;
    private final TransactionClock clock;

    public TransactionController(TransactionFacade facade, TransactionRepository transactions, TransactionClock clock) {
        this.facade = facade;
        this.transactions = transactions;
        this.clock = clock;
    }

    @PostMapping
    public ResponseEntity<TransactionResponse> submit(
            @RequestHeader(IDEMPOTENCY_KEY) @NotBlank @Size(max = 64) String idempotencyKey,
            @RequestHeader(value = SIMULATED_TIME, required = false) String simulatedTime,
            @Valid @RequestBody SubmitTransactionRequest request) {

        TransactionCommand command = new TransactionCommand(
                request.type(), request.sourceAccountId(), request.destinationAccountId(), request.amount());
        TransactionFacade.Outcome outcome = facade.submit(idempotencyKey, command, clock.eventTime(simulatedTime));
        Transaction tx = outcome.transaction();

        HttpStatus status;
        if (!tx.isCompleted()) {
            status = HttpStatus.UNPROCESSABLE_ENTITY;
        } else {
            status = outcome.replayed() ? HttpStatus.OK : HttpStatus.CREATED;
        }
        return ResponseEntity.status(status)
                .location(URI.create("/api/v1/transactions/" + tx.getId()))
                .header(REPLAY_HEADER, Boolean.toString(outcome.replayed()))
                .body(TransactionResponse.from(tx));
    }

    @GetMapping("/{id}")
    public TransactionResponse get(@PathVariable UUID id) {
        return transactions.findById(id)
                .map(TransactionResponse::from)
                .orElseThrow(() -> new NotFoundException("Transaction", id));
    }

    // ---- DTOs -------------------------------------------------------------

    /** Amount capped at 10 000 000 XOF per transaction (fictional regulatory limit). */
    public record SubmitTransactionRequest(
            @NotNull TransactionType type,
            @NotNull UUID sourceAccountId,
            @NotNull UUID destinationAccountId,
            @NotNull @Positive @Max(10_000_000) Long amount) {}

    public record TransactionResponse(
            UUID id, String idempotencyKey, TransactionType type, TransactionStatus status,
            UUID sourceAccountId, UUID destinationAccountId, long amount, long fee, String currency,
            String failureReason, Instant occurredAt, Instant recordedAt) {

        static TransactionResponse from(Transaction t) {
            return new TransactionResponse(t.getId(), t.getIdempotencyKey(), t.getType(), t.getStatus(),
                    t.getSourceAccountId(), t.getDestinationAccountId(), t.getAmount(), t.getFee(),
                    t.getCurrency(), t.getFailureReason(), t.getOccurredAt(), t.getRecordedAt());
        }
    }
}
