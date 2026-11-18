package io.mmplatform.paymentcore.transaction;

import io.mmplatform.paymentcore.config.PlatformProperties;
import org.springframework.stereotype.Component;

/**
 * Computes fees with integer arithmetic only (ADR 0005).
 * fee = floor(amount × bps / 10 000), capped at {@code maxFee}.
 */
@Component
public class FeePolicy {

    private static final long BPS_DENOMINATOR = 10_000L;

    private final PlatformProperties.Fees fees;

    public FeePolicy(PlatformProperties properties) {
        this.fees = properties.fees();
    }

    public long feeFor(TransactionType type, long amount) {
        long bps = switch (type) {
            case TRANSFER -> fees.transferBps();
            case CASH_OUT -> fees.cashOutBps();
            case FLOAT_TOPUP, CASH_IN, PAYMENT -> 0L;
        };
        if (bps == 0L) {
            return 0L;
        }
        long fee = Math.multiplyExact(amount, bps) / BPS_DENOMINATOR; // integer division = floor for positives
        return Math.min(fee, fees.maxFee());
    }
}
