package io.mmplatform.paymentcore.common;

/**
 * The request is well-formed but violates a business rule that the client should
 * have respected (e.g. CASH_IN to a merchant) → HTTP 422. Nothing is recorded.
 */
public class InvalidRequestException extends RuntimeException {

    public InvalidRequestException(String message) {
        super(message);
    }
}
