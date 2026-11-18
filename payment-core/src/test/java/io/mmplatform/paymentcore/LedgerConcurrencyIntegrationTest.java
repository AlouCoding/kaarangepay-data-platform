package io.mmplatform.paymentcore;

import static org.assertj.core.api.Assertions.assertThat;

import io.mmplatform.paymentcore.account.Account;
import io.mmplatform.paymentcore.account.AccountRepository;
import io.mmplatform.paymentcore.account.AccountService;
import io.mmplatform.paymentcore.account.AccountType;
import io.mmplatform.paymentcore.ledger.LedgerIntegrityService;
import io.mmplatform.paymentcore.transaction.TransactionCommand;
import io.mmplatform.paymentcore.transaction.TransactionFacade;
import io.mmplatform.paymentcore.transaction.TransactionStatus;
import io.mmplatform.paymentcore.transaction.TransactionType;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Random;
import java.util.UUID;
import java.util.concurrent.Callable;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;

/**
 * The tests a fintech reviewer looks for first: does the ledger stay correct
 * when many transfers hit the same accounts at the same time?
 */
class LedgerConcurrencyIntegrationTest extends AbstractIntegrationTest {

    private static final UUID TREASURY = UUID.fromString("00000000-0000-0000-0000-000000000001");
    private static final UUID FEES = UUID.fromString("00000000-0000-0000-0000-000000000002");

    @Autowired TransactionFacade facade;
    @Autowired AccountService accountService;
    @Autowired AccountRepository accountRepository;
    @Autowired LedgerIntegrityService integrity;

    @Test
    void randomConcurrentTransfersNeverCreateOrDestroyMoney() throws Exception {
        int customersCount = 20;
        long initialPerCustomer = 100_000;

        UUID agent = open(AccountType.AGENT);
        submit(TransactionType.FLOAT_TOPUP, TREASURY, agent, customersCount * initialPerCustomer);
        List<UUID> customers = new ArrayList<>();
        for (int i = 0; i < customersCount; i++) {
            UUID c = open(AccountType.CUSTOMER);
            submit(TransactionType.CASH_IN, agent, c, initialPerCustomer);
            customers.add(c);
        }
        long feesBefore = balance(FEES);

        // 16 threads × 250 random transfers between the same 20 wallets: heavy contention.
        int threads = 16;
        int transfersPerThread = 250;
        ExecutorService pool = Executors.newFixedThreadPool(threads);
        CountDownLatch start = new CountDownLatch(1);
        List<Future<Integer>> results = new ArrayList<>();
        for (int t = 0; t < threads; t++) {
            long seed = t;
            results.add(pool.submit(() -> {
                Random random = new Random(seed);
                start.await();
                int completed = 0;
                for (int i = 0; i < transfersPerThread; i++) {
                    UUID from = customers.get(random.nextInt(customersCount));
                    UUID to = customers.get(random.nextInt(customersCount));
                    if (from.equals(to)) {
                        continue;
                    }
                    long amount = 1 + random.nextInt(20_000);
                    if (submit(TransactionType.TRANSFER, from, to, amount) == TransactionStatus.COMPLETED) {
                        completed++;
                    }
                }
                return completed;
            }));
        }
        start.countDown();
        int completed = 0;
        for (Future<Integer> f : results) {
            completed += f.get(2, TimeUnit.MINUTES); // also surfaces any exception (e.g. deadlock)
        }
        pool.shutdown();

        long customersTotal = customers.stream().mapToLong(this::balance).sum();
        long feesCollected = balance(FEES) - feesBefore;

        assertThat(completed).as("some transfers must succeed").isPositive();
        assertThat(customers).allSatisfy(c -> assertThat(balance(c)).isNotNegative());
        // Money only moved between customers and the fee account: nothing created, nothing lost.
        assertThat(customersTotal + feesCollected).isEqualTo(customersCount * initialPerCustomer);
        assertThat(integrity.check().healthy()).isTrue();
    }

    @Test
    void concurrentRetriesOfTheSameRequestExecuteExactlyOnce() throws Exception {
        UUID agent = open(AccountType.AGENT);
        submit(TransactionType.FLOAT_TOPUP, TREASURY, agent, 1_000_000);
        UUID alice = open(AccountType.CUSTOMER);

        String key = UUID.randomUUID().toString();
        TransactionCommand command = new TransactionCommand(TransactionType.CASH_IN, agent, alice, 50_000);

        int attempts = 10;
        ExecutorService pool = Executors.newFixedThreadPool(attempts);
        CountDownLatch start = new CountDownLatch(1);
        List<Future<TransactionFacade.Outcome>> outcomes = new ArrayList<>();
        for (int i = 0; i < attempts; i++) {
            Callable<TransactionFacade.Outcome> call = () -> {
                start.await();
                return facade.submit(key, command, Instant.now());
            };
            outcomes.add(pool.submit(call));
        }
        start.countDown();

        int executed = 0;
        UUID firstId = null;
        for (Future<TransactionFacade.Outcome> f : outcomes) {
            TransactionFacade.Outcome outcome = f.get(1, TimeUnit.MINUTES);
            if (!outcome.replayed()) {
                executed++;
            }
            if (firstId == null) {
                firstId = outcome.transaction().getId();
            }
            assertThat(outcome.transaction().getId()).isEqualTo(firstId);
        }
        pool.shutdown();

        assertThat(executed).isEqualTo(1);
        assertThat(balance(alice)).isEqualTo(50_000);
        assertThat(integrity.check().healthy()).isTrue();
    }

    // ---- helpers ----------------------------------------------------------

    private UUID open(AccountType type) {
        Account account = accountService.open(PaymentApiIntegrationTest.randomPhone(), "Load test", type);
        return account.getId();
    }

    private TransactionStatus submit(TransactionType type, UUID from, UUID to, long amount) {
        return facade.submit(UUID.randomUUID().toString(), new TransactionCommand(type, from, to, amount), Instant.now())
                .transaction().getStatus();
    }

    private long balance(UUID id) {
        return accountRepository.findById(id).orElseThrow().getBalance();
    }
}
