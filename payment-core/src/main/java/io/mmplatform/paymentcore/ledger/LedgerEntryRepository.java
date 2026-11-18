package io.mmplatform.paymentcore.ledger;

import java.util.List;
import java.util.UUID;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;

public interface LedgerEntryRepository extends JpaRepository<LedgerEntry, Long> {

    List<LedgerEntry> findByAccountIdOrderByIdDesc(UUID accountId, Pageable pageable);

    List<LedgerEntry> findByTransactionId(UUID transactionId);
}
