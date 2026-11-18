package io.mmplatform.paymentcore.config;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.PositiveOrZero;
import java.util.UUID;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.validation.annotation.Validated;

/** Typed view of the {@code platform.*} configuration (see application.yml). */
@Validated
@ConfigurationProperties(prefix = "platform")
public record PlatformProperties(
        @Valid @NotNull SystemAccounts systemAccounts,
        @Valid @NotNull Fees fees,
        @Valid @NotNull Simulation simulation) {

    /** Fixed ids of the system accounts seeded by Flyway (V1). */
    public record SystemAccounts(@NotNull UUID treasuryId, @NotNull UUID feesId) {}

    /** Fee schedule in basis points (100 bps = 1 %), capped at {@code maxFee} XOF. */
    public record Fees(
            @PositiveOrZero long transferBps,
            @PositiveOrZero long cashOutBps,
            @PositiveOrZero long maxFee) {}

    /** Dev/demo switches. See docs/adr/0004. */
    public record Simulation(boolean allowClientClock) {}
}
