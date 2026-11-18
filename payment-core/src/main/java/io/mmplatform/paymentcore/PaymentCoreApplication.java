package io.mmplatform.paymentcore;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.ConfigurationPropertiesScan;

/**
 * Transactional core of the mobile money platform.
 *
 * <p>Modules (one package each): {@code account}, {@code ledger}, {@code transaction}.
 * See docs/adr/0001 for why this is a modular monolith.
 */
@SpringBootApplication
@ConfigurationPropertiesScan
public class PaymentCoreApplication {

    public static void main(String[] args) {
        SpringApplication.run(PaymentCoreApplication.class, args);
    }
}
