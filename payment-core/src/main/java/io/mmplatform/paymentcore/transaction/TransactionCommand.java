package io.mmplatform.paymentcore.transaction;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import java.util.Objects;
import java.util.UUID;

/** What the client asks for, independent of HTTP. */
public record TransactionCommand(
        TransactionType type,
        UUID sourceAccountId,
        UUID destinationAccountId,
        long amount) {

    public TransactionCommand {
        Objects.requireNonNull(type, "type");
        Objects.requireNonNull(sourceAccountId, "sourceAccountId");
        Objects.requireNonNull(destinationAccountId, "destinationAccountId");
        if (amount <= 0) {
            throw new IllegalArgumentException("amount must be positive");
        }
    }

    /**
     * SHA-256 of the business payload. Two requests with the same idempotency key
     * must have the same hash, otherwise the key is being reused by mistake (ADR 0003).
     */
    public String requestHash() {
        String canonical = String.join("|",
                type.name(), sourceAccountId.toString(), destinationAccountId.toString(), Long.toString(amount));
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256")
                    .digest(canonical.getBytes(StandardCharsets.UTF_8));
            return HexFormat.of().formatHex(digest);
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException("SHA-256 is guaranteed by the JDK", e);
        }
    }
}
