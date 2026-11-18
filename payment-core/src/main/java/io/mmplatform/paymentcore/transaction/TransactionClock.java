package io.mmplatform.paymentcore.transaction;

import io.mmplatform.paymentcore.common.InvalidRequestException;
import io.mmplatform.paymentcore.config.PlatformProperties;
import java.time.Clock;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.format.DateTimeParseException;
import org.springframework.lang.Nullable;
import org.springframework.stereotype.Component;

/**
 * Resolves the event time of a transaction (ADR 0004).
 * The only place where a client-provided time can enter the system.
 */
@Component
public class TransactionClock {

    private final Clock clock;
    private final boolean allowClientClock;

    public TransactionClock(Clock clock, PlatformProperties properties) {
        this.clock = clock;
        this.allowClientClock = properties.simulation().allowClientClock();
    }

    /** Server time, or the simulated time from the header when the dev flag is on. */
    public Instant eventTime(@Nullable String simulatedTimeHeader) {
        if (simulatedTimeHeader == null || simulatedTimeHeader.isBlank()) {
            return clock.instant();
        }
        if (!allowClientClock) {
            throw new InvalidRequestException(
                    "X-Simulated-Time is disabled on this server (platform.simulation.allow-client-clock=false)");
        }
        try {
            return OffsetDateTime.parse(simulatedTimeHeader).toInstant();
        } catch (DateTimeParseException e) {
            throw new InvalidRequestException("X-Simulated-Time must be ISO-8601 with offset, e.g. 2026-11-25T08:30:00Z");
        }
    }

    /** Processing time: always the real server clock. */
    public Instant processingTime() {
        return clock.instant();
    }
}
