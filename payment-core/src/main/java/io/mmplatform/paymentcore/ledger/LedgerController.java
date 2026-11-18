package io.mmplatform.paymentcore.ledger;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/ledger")
public class LedgerController {

    private final LedgerIntegrityService integrity;

    public LedgerController(LedgerIntegrityService integrity) {
        this.integrity = integrity;
    }

    /** 200 if all invariants hold, 500 otherwise — usable as a monitoring probe. */
    @GetMapping("/integrity")
    public ResponseEntity<LedgerIntegrityService.IntegrityReport> integrity() {
        LedgerIntegrityService.IntegrityReport report = integrity.check();
        HttpStatus status = report.healthy() ? HttpStatus.OK : HttpStatus.INTERNAL_SERVER_ERROR;
        return ResponseEntity.status(status).body(report);
    }
}
