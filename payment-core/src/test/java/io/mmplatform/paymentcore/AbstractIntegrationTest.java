package io.mmplatform.paymentcore;

import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.testcontainers.service.connection.ServiceConnection;
import org.testcontainers.containers.PostgreSQLContainer;

/**
 * Base class for tests against a real PostgreSQL (Testcontainers).
 *
 * <p>Singleton-container pattern: one database for the whole test run, started once.
 * (A {@code @Container} field per class would be stopped while Spring still caches a
 * context pointing at it.) Tests must therefore not assume an empty database.
 */
@SpringBootTest(
        webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
        properties = {
                "platform.simulation.allow-client-clock=true",
                "spring.datasource.hikari.maximum-pool-size=32"
        })
public abstract class AbstractIntegrationTest {

    @ServiceConnection
    static final PostgreSQLContainer<?> POSTGRES = new PostgreSQLContainer<>("postgres:16-alpine");

    static {
        POSTGRES.start();
    }
}
