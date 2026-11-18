package io.mmplatform.paymentcore;

import static org.assertj.core.api.Assertions.assertThat;

import io.mmplatform.paymentcore.account.AccountController.AccountResponse;
import io.mmplatform.paymentcore.ledger.LedgerIntegrityService.IntegrityReport;
import io.mmplatform.paymentcore.transaction.TransactionController.TransactionResponse;
import io.mmplatform.paymentcore.transaction.TransactionStatus;
import java.time.Instant;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ThreadLocalRandom;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.web.client.TestRestTemplate;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;

/** End-to-end tests through HTTP, against a real PostgreSQL. */
class PaymentApiIntegrationTest extends AbstractIntegrationTest {

    static final UUID TREASURY = UUID.fromString("00000000-0000-0000-0000-000000000001");
    static final UUID FEES = UUID.fromString("00000000-0000-0000-0000-000000000002");

    @Autowired
    TestRestTemplate http;

    @AfterEach
    void ledgerIsAlwaysConsistent() {
        ResponseEntity<IntegrityReport> report = http.getForEntity("/api/v1/ledger/integrity", IntegrityReport.class);
        assertThat(report.getStatusCode()).isEqualTo(HttpStatus.OK);
        assertThat(report.getBody()).isNotNull();
        assertThat(report.getBody().healthy()).as("ledger invariants: %s", report.getBody()).isTrue();
    }

    @Test
    void fullMoneyFlowMovesMoneyAndChargesFees() {
        UUID agent = open("AGENT");
        UUID alice = open("CUSTOMER");
        UUID bob = open("CUSTOMER");
        long feesBefore = balance(FEES);

        assertThat(post("FLOAT_TOPUP", TREASURY, agent, 1_000_000).getStatusCode()).isEqualTo(HttpStatus.CREATED);
        assertThat(post("CASH_IN", agent, alice, 100_000).getStatusCode()).isEqualTo(HttpStatus.CREATED);

        ResponseEntity<TransactionResponse> transfer = post("TRANSFER", alice, bob, 10_000);
        assertThat(transfer.getStatusCode()).isEqualTo(HttpStatus.CREATED);
        assertThat(transfer.getBody().fee()).isEqualTo(100);

        assertThat(balance(agent)).isEqualTo(900_000);
        assertThat(balance(alice)).isEqualTo(100_000 - 10_000 - 100);
        assertThat(balance(bob)).isEqualTo(10_000);
        assertThat(balance(FEES) - feesBefore).isEqualTo(100);
    }

    @Test
    void merchantCanWithdrawTakingsAtAnAgent() {
        UUID agent = fundedAgent(500_000);
        UUID alice = open("CUSTOMER");
        UUID shop = open("MERCHANT");
        post("CASH_IN", agent, alice, 100_000);
        post("PAYMENT", alice, shop, 40_000);

        ResponseEntity<TransactionResponse> withdrawal = post("CASH_OUT", shop, agent, 30_000);

        assertThat(withdrawal.getStatusCode()).isEqualTo(HttpStatus.CREATED);
        assertThat(withdrawal.getBody().fee()).isEqualTo(150); // 0.5 % cash-out fee
        assertThat(balance(shop)).isEqualTo(40_000 - 30_000 - 150);
    }

    @Test
    void insufficientFundsIsRecordedAsFailedAndMovesNothing() {
        UUID alice = open("CUSTOMER");
        UUID bob = open("CUSTOMER");

        ResponseEntity<TransactionResponse> response = post("TRANSFER", alice, bob, 5_000);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.UNPROCESSABLE_ENTITY);
        assertThat(response.getBody().status()).isEqualTo(TransactionStatus.FAILED);
        assertThat(response.getBody().failureReason()).isEqualTo("INSUFFICIENT_FUNDS");
        assertThat(balance(alice)).isZero();
        assertThat(balance(bob)).isZero();
    }

    @Test
    void retryWithSameKeyIsReplayedAndDebitsOnce() {
        UUID agent = fundedAgent(500_000);
        UUID alice = open("CUSTOMER");
        String key = UUID.randomUUID().toString();

        ResponseEntity<TransactionResponse> first = post(key, "CASH_IN", agent, alice, 20_000, null);
        ResponseEntity<TransactionResponse> retry = post(key, "CASH_IN", agent, alice, 20_000, null);

        assertThat(first.getStatusCode()).isEqualTo(HttpStatus.CREATED);
        assertThat(first.getHeaders().getFirst("Idempotent-Replay")).isEqualTo("false");
        assertThat(retry.getStatusCode()).isEqualTo(HttpStatus.OK);
        assertThat(retry.getHeaders().getFirst("Idempotent-Replay")).isEqualTo("true");
        assertThat(retry.getBody().id()).isEqualTo(first.getBody().id());
        assertThat(balance(alice)).isEqualTo(20_000);
    }

    @Test
    void reusingAKeyWithADifferentPayloadIsAConflict() {
        UUID agent = fundedAgent(500_000);
        UUID alice = open("CUSTOMER");
        String key = UUID.randomUUID().toString();

        post(key, "CASH_IN", agent, alice, 20_000, null);
        ResponseEntity<String> conflict = postRaw(key, "CASH_IN", agent, alice, 30_000);

        assertThat(conflict.getStatusCode()).isEqualTo(HttpStatus.CONFLICT);
        assertThat(balance(alice)).isEqualTo(20_000);
    }

    @Test
    void invalidRoutingIsRejectedWithoutBeingRecorded() {
        UUID agent = fundedAgent(500_000);
        UUID merchant = open("MERCHANT");

        ResponseEntity<String> response = postRaw(UUID.randomUUID().toString(), "CASH_IN", agent, merchant, 1_000);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.UNPROCESSABLE_ENTITY);
        assertThat(response.getBody()).contains("CASH_IN is not allowed from AGENT to MERCHANT");
        assertThat(balance(merchant)).isZero();
    }

    @Test
    void blockedAccountCannotReceiveMoney() {
        UUID agent = fundedAgent(500_000);
        UUID alice = open("CUSTOMER");
        http.exchange("/api/v1/accounts/" + alice + "/status", HttpMethod.PUT,
                new HttpEntity<>(Map.of("status", "BLOCKED")), AccountResponse.class);

        ResponseEntity<TransactionResponse> response = post("CASH_IN", agent, alice, 1_000);

        assertThat(response.getBody().failureReason()).isEqualTo("ACCOUNT_BLOCKED");
        assertThat(balance(alice)).isZero();
    }

    @Test
    void simulatedTimeBecomesEventTimeButNotProcessingTime() {
        UUID agent = fundedAgent(500_000);
        UUID alice = open("CUSTOMER");

        ResponseEntity<TransactionResponse> response =
                post(UUID.randomUUID().toString(), "CASH_IN", agent, alice, 1_000, "2026-11-30T18:45:00Z");

        assertThat(response.getBody().occurredAt()).isEqualTo(Instant.parse("2026-11-30T18:45:00Z"));
        assertThat(response.getBody().recordedAt()).isNotEqualTo(response.getBody().occurredAt());
    }

    @Test
    void missingIdempotencyKeyIsABadRequest() {
        HttpHeaders headers = new HttpHeaders();
        Map<String, Object> body = Map.of("type", "TRANSFER", "sourceAccountId", UUID.randomUUID(),
                "destinationAccountId", UUID.randomUUID(), "amount", 100);
        ResponseEntity<String> response =
                http.postForEntity("/api/v1/transactions", new HttpEntity<>(body, headers), String.class);
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.BAD_REQUEST);
    }

    @Test
    void systemAccountsCannotBeOpenedThroughTheApi() {
        ResponseEntity<String> response = http.postForEntity("/api/v1/accounts",
                Map.of("phone", randomPhone(), "ownerName", "Hacker", "type", "SYSTEM"), String.class);
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.UNPROCESSABLE_ENTITY);
    }

    // ---- helpers ----------------------------------------------------------

    private UUID open(String type) {
        ResponseEntity<AccountResponse> response = http.postForEntity("/api/v1/accounts",
                Map.of("phone", randomPhone(), "ownerName", "Test " + type, "type", type), AccountResponse.class);
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.CREATED);
        return response.getBody().id();
    }

    private UUID fundedAgent(long amount) {
        UUID agent = open("AGENT");
        assertThat(post("FLOAT_TOPUP", TREASURY, agent, amount).getStatusCode()).isEqualTo(HttpStatus.CREATED);
        return agent;
    }

    private long balance(UUID account) {
        return http.getForObject("/api/v1/accounts/" + account, AccountResponse.class).balance();
    }

    private ResponseEntity<TransactionResponse> post(String type, UUID from, UUID to, long amount) {
        return post(UUID.randomUUID().toString(), type, from, to, amount, null);
    }

    private ResponseEntity<TransactionResponse> post(String key, String type, UUID from, UUID to, long amount,
                                                     String simulatedTime) {
        return http.postForEntity("/api/v1/transactions",
                request(key, type, from, to, amount, simulatedTime), TransactionResponse.class);
    }

    private ResponseEntity<String> postRaw(String key, String type, UUID from, UUID to, long amount) {
        return http.postForEntity("/api/v1/transactions", request(key, type, from, to, amount, null), String.class);
    }

    private static HttpEntity<Map<String, Object>> request(String key, String type, UUID from, UUID to, long amount,
                                                           String simulatedTime) {
        HttpHeaders headers = new HttpHeaders();
        headers.set("Idempotency-Key", key);
        if (simulatedTime != null) {
            headers.set("X-Simulated-Time", simulatedTime);
        }
        return new HttpEntity<>(Map.of("type", type, "sourceAccountId", from,
                "destinationAccountId", to, "amount", amount), headers);
    }

    static String randomPhone() {
        return "+2217" + ThreadLocalRandom.current().nextLong(10_000_000L, 99_999_999L);
    }
}
