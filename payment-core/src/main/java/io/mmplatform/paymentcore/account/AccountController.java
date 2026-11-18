package io.mmplatform.paymentcore.account;

import io.mmplatform.paymentcore.ledger.LedgerEntry;
import io.mmplatform.paymentcore.ledger.LedgerEntryRepository;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
import java.net.URI;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import org.springframework.data.domain.PageRequest;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/accounts")
public class AccountController {

    private final AccountService service;
    private final LedgerEntryRepository entries;

    public AccountController(AccountService service, LedgerEntryRepository entries) {
        this.service = service;
        this.entries = entries;
    }

    @PostMapping
    public ResponseEntity<AccountResponse> open(@Valid @RequestBody OpenAccountRequest request) {
        Account account = service.open(request.phone(), request.ownerName(), request.type());
        return ResponseEntity
                .created(URI.create("/api/v1/accounts/" + account.getId()))
                .body(AccountResponse.from(account));
    }

    @GetMapping("/{id}")
    public AccountResponse get(@PathVariable UUID id) {
        return AccountResponse.from(service.get(id));
    }

    @PutMapping("/{id}/status")
    public AccountResponse changeStatus(@PathVariable UUID id, @Valid @RequestBody ChangeStatusRequest request) {
        return AccountResponse.from(service.changeStatus(id, request.status()));
    }

    /** Most recent ledger entries of the account (its statement), newest first. */
    @GetMapping("/{id}/entries")
    public List<EntryResponse> statement(
            @PathVariable UUID id,
            @RequestParam(defaultValue = "50") @Min(1) @Max(500) int limit) {
        service.get(id); // 404 if the account does not exist
        return entries.findByAccountIdOrderByIdDesc(id, PageRequest.ofSize(limit)).stream()
                .map(EntryResponse::from)
                .toList();
    }

    // ---- DTOs -------------------------------------------------------------

    public record OpenAccountRequest(
            @NotBlank @Pattern(regexp = "^\\+?[0-9]{8,15}$", message = "must be a phone number") String phone,
            @NotBlank @Size(max = 120) String ownerName,
            @NotNull AccountType type) {}

    public record ChangeStatusRequest(@NotNull AccountStatus status) {}

    public record AccountResponse(
            UUID id, String phone, String ownerName, AccountType type, AccountStatus status,
            String currency, long balance, Instant createdAt) {

        static AccountResponse from(Account a) {
            return new AccountResponse(a.getId(), a.getPhone(), a.getOwnerName(), a.getType(),
                    a.getStatus(), a.getCurrency(), a.getBalance(), a.getCreatedAt());
        }
    }

    public record EntryResponse(
            long id, UUID transactionId, String direction, long amount, long balanceAfter, Instant occurredAt) {

        static EntryResponse from(LedgerEntry e) {
            return new EntryResponse(e.getId(), e.getTransactionId(), e.getDirection().name(),
                    e.getAmount(), e.getBalanceAfter(), e.getOccurredAt());
        }
    }
}
