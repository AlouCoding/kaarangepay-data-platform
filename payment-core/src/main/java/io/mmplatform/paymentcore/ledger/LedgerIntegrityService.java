package io.mmplatform.paymentcore.ledger;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;

/**
 * Checks the three ledger invariants of docs/adr/0002 directly in SQL.
 * The same checks will be reimplemented as dbt tests on the warehouse (phase 4):
 * comparing both is a real reconciliation between OLTP and analytics.
 */
@Service
public class LedgerIntegrityService {

    private static final String SUM_OF_BALANCES =
            "SELECT COALESCE(SUM(balance), 0) FROM accounts";

    private static final String UNBALANCED_TRANSACTIONS = """
            SELECT COUNT(*) FROM (
                SELECT transaction_id
                FROM ledger_entries
                GROUP BY transaction_id
                HAVING SUM(CASE WHEN direction = 'CREDIT' THEN amount ELSE -amount END) <> 0
            ) t
            """;

    private static final String ACCOUNTS_WITH_DRIFT = """
            SELECT COUNT(*)
            FROM accounts a
            LEFT JOIN (
                SELECT account_id,
                       SUM(CASE WHEN direction = 'CREDIT' THEN amount ELSE -amount END) AS net
                FROM ledger_entries
                GROUP BY account_id
            ) e ON e.account_id = a.id
            WHERE a.balance <> COALESCE(e.net, 0)
            """;

    private final JdbcTemplate jdbc;

    public LedgerIntegrityService(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    /** REPEATABLE READ: the three queries see the same snapshot of the database. */
    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    public IntegrityReport check() {
        long sumOfBalances = queryLong(SUM_OF_BALANCES);
        long unbalanced = queryLong(UNBALANCED_TRANSACTIONS);
        long drift = queryLong(ACCOUNTS_WITH_DRIFT);
        return new IntegrityReport(sumOfBalances, unbalanced, drift,
                sumOfBalances == 0 && unbalanced == 0 && drift == 0);
    }

    private long queryLong(String sql) {
        Long value = jdbc.queryForObject(sql, Long.class);
        return value == null ? 0L : value;
    }

    /**
     * @param sumOfBalances           must be 0 (TREASURY mirrors all e-money issued)
     * @param unbalancedTransactions  transactions whose debits ≠ credits — must be 0
     * @param accountsWithDrift       accounts whose cached balance ≠ ledger net — must be 0
     */
    public record IntegrityReport(long sumOfBalances, long unbalancedTransactions,
                                  long accountsWithDrift, boolean healthy) {}
}
