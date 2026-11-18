package io.mmplatform.paymentcore.transaction;

import static io.mmplatform.paymentcore.account.AccountType.AGENT;
import static io.mmplatform.paymentcore.account.AccountType.CUSTOMER;
import static io.mmplatform.paymentcore.account.AccountType.MERCHANT;
import static io.mmplatform.paymentcore.account.AccountType.SYSTEM;
import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import io.mmplatform.paymentcore.common.InvalidRequestException;
import io.mmplatform.paymentcore.config.PlatformProperties;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.UUID;
import org.junit.jupiter.api.Test;

/** Pure unit tests: routing rules, request hashing, event-time resolution. */
class TransactionRulesTest {

    @Test
    void routingMatrix() {
        assertThat(TransactionType.FLOAT_TOPUP.allows(SYSTEM, AGENT)).isTrue();
        assertThat(TransactionType.CASH_IN.allows(AGENT, CUSTOMER)).isTrue();
        assertThat(TransactionType.CASH_OUT.allows(CUSTOMER, AGENT)).isTrue();
        assertThat(TransactionType.CASH_OUT.allows(MERCHANT, AGENT)).isTrue(); // merchant takings (v1.1)
        assertThat(TransactionType.TRANSFER.allows(CUSTOMER, CUSTOMER)).isTrue();
        assertThat(TransactionType.PAYMENT.allows(CUSTOMER, MERCHANT)).isTrue();

        assertThat(TransactionType.CASH_IN.allows(AGENT, MERCHANT)).isFalse();
        assertThat(TransactionType.TRANSFER.allows(CUSTOMER, SYSTEM)).isFalse();
        assertThat(TransactionType.PAYMENT.allows(MERCHANT, CUSTOMER)).isFalse();
        assertThat(TransactionType.FLOAT_TOPUP.allows(AGENT, AGENT)).isFalse();
    }

    @Test
    void requestHashIsStableAndPayloadSensitive() {
        UUID a = UUID.randomUUID();
        UUID b = UUID.randomUUID();
        TransactionCommand cmd = new TransactionCommand(TransactionType.TRANSFER, a, b, 5_000);

        assertThat(cmd.requestHash())
                .hasSize(64)
                .isEqualTo(new TransactionCommand(TransactionType.TRANSFER, a, b, 5_000).requestHash())
                .isNotEqualTo(new TransactionCommand(TransactionType.TRANSFER, a, b, 5_001).requestHash())
                .isNotEqualTo(new TransactionCommand(TransactionType.TRANSFER, b, a, 5_000).requestHash());
    }

    @Test
    void commandRejectsNonPositiveAmounts() {
        assertThatThrownBy(() -> new TransactionCommand(TransactionType.TRANSFER, UUID.randomUUID(), UUID.randomUUID(), 0))
                .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void eventTimeDefaultsToServerClock() {
        Instant now = Instant.parse("2026-11-17T10:00:00Z");
        TransactionClock clock = clock(now, false);
        assertThat(clock.eventTime(null)).isEqualTo(now);
        assertThat(clock.eventTime(" ")).isEqualTo(now);
    }

    @Test
    void simulatedTimeIsRejectedUnlessEnabled() {
        TransactionClock clock = clock(Instant.now(), false);
        assertThatThrownBy(() -> clock.eventTime("2026-11-25T08:30:00Z"))
                .isInstanceOf(InvalidRequestException.class)
                .hasMessageContaining("disabled");
    }

    @Test
    void simulatedTimeIsUsedWhenEnabled() {
        TransactionClock clock = clock(Instant.now(), true);
        assertThat(clock.eventTime("2026-11-25T08:30:00+00:00"))
                .isEqualTo(Instant.parse("2026-11-25T08:30:00Z"));
        assertThatThrownBy(() -> clock.eventTime("yesterday"))
                .isInstanceOf(InvalidRequestException.class);
    }

    private static TransactionClock clock(Instant now, boolean allowClientClock) {
        PlatformProperties props = new PlatformProperties(
                new PlatformProperties.SystemAccounts(UUID.randomUUID(), UUID.randomUUID()),
                new PlatformProperties.Fees(0, 0, 0),
                new PlatformProperties.Simulation(allowClientClock));
        return new TransactionClock(Clock.fixed(now, ZoneOffset.UTC), props);
    }
}
