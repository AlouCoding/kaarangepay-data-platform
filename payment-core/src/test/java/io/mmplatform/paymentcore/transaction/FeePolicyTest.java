package io.mmplatform.paymentcore.transaction;

import static org.assertj.core.api.Assertions.assertThat;

import io.mmplatform.paymentcore.config.PlatformProperties;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.junit.jupiter.params.provider.EnumSource;

class FeePolicyTest {

    private final FeePolicy policy = new FeePolicy(new PlatformProperties(
            new PlatformProperties.SystemAccounts(UUID.randomUUID(), UUID.randomUUID()),
            new PlatformProperties.Fees(100, 50, 5_000),
            new PlatformProperties.Simulation(false)));

    @ParameterizedTest(name = "TRANSFER of {0} XOF costs {1} XOF")
    @CsvSource({
            "10000, 100",     // 1 %
            "99, 0",          // floor(0.99) = 0, rounded in the customer's favour
            "150, 1",         // floor(1.5) = 1
            "500000, 5000",   // exactly the cap
            "2000000, 5000"   // capped
    })
    void transferFeeIsOnePercentRoundedDownAndCapped(long amount, long expectedFee) {
        assertThat(policy.feeFor(TransactionType.TRANSFER, amount)).isEqualTo(expectedFee);
    }

    @Test
    void cashOutFeeIsHalfAPercent() {
        assertThat(policy.feeFor(TransactionType.CASH_OUT, 10_000)).isEqualTo(50);
    }

    @ParameterizedTest
    @EnumSource(value = TransactionType.class, names = {"FLOAT_TOPUP", "CASH_IN", "PAYMENT"})
    void freeTransactionTypes(TransactionType type) {
        assertThat(policy.feeFor(type, 1_000_000)).isZero();
    }
}
