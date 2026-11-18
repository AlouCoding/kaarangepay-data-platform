package io.mmplatform.paymentcore.account;

import jakarta.persistence.LockModeType;
import java.util.Collection;
import java.util.List;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface AccountRepository extends JpaRepository<Account, UUID> {

    boolean existsByPhone(String phone);

    /**
     * Locks the given accounts (SELECT ... FOR UPDATE) <b>always in id order</b>.
     * A global lock order makes deadlocks between concurrent transfers impossible.
     */
    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("select a from Account a where a.id in :ids order by a.id")
    List<Account> lockAllByIdIn(@Param("ids") Collection<UUID> ids);
}
