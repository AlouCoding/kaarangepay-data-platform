package io.mmplatform.paymentcore.common;

/** A requested resource does not exist → HTTP 404. */
public class NotFoundException extends RuntimeException {

    public NotFoundException(String resource, Object id) {
        super(resource + " not found: " + id);
    }
}
