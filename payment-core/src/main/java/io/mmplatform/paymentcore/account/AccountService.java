package io.mmplatform.paymentcore.account;

import io.mmplatform.paymentcore.common.InvalidRequestException;
import io.mmplatform.paymentcore.common.NotFoundException;
import java.time.Clock;
import java.util.UUID;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class AccountService {

    private final AccountRepository accounts;
    private final Clock clock;

    public AccountService(AccountRepository accounts, Clock clock) {
        this.accounts = accounts;
        this.clock = clock;
    }

    @Transactional
    public Account open(String phone, String ownerName, AccountType type) {
        if (type == AccountType.SYSTEM) {
            throw new InvalidRequestException("SYSTEM accounts cannot be opened through the API");
        }
        if (accounts.existsByPhone(phone)) {
            throw new InvalidRequestException("An account already exists for phone " + phone);
        }
        try {
            return accounts.saveAndFlush(Account.open(phone, ownerName, type, clock.instant()));
        } catch (DataIntegrityViolationException e) {
            // Two concurrent requests for the same phone: the UNIQUE constraint wins.
            throw new InvalidRequestException("An account already exists for phone " + phone);
        }
    }

    @Transactional(readOnly = true)
    public Account get(UUID id) {
        return accounts.findById(id).orElseThrow(() -> new NotFoundException("Account", id));
    }

    @Transactional
    public Account changeStatus(UUID id, AccountStatus status) {
        Account account = get(id);
        if (account.isSystem()) {
            throw new InvalidRequestException("System accounts cannot be blocked");
        }
        account.changeStatus(status, clock.instant());
        return account;
    }
}
