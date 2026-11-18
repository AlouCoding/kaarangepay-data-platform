package io.mmplatform.paymentcore.common;

/** The idempotency key was already used with a different payload → HTTP 409. */
public class IdempotencyConflictException extends RuntimeException {

    public IdempotencyConflictException(String key) {
        super("Idempotency-Key '" + key + "' was already used with a different request payload");
    }
}
