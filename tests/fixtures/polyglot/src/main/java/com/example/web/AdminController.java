package com.example.web;

import com.example.repo.UserRepository;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class AdminController {
    private final UserRepository repository = new UserRepository();

    @GetMapping("/admin")
    @PreAuthorize("hasRole('ADMIN')")
    public ResponseEntity<String> audit(@RequestParam(required = false) String userId) {
        if (userId == null || userId.isBlank()) {
            throw new IllegalArgumentException("userId");
        }
        return ResponseEntity.ok(this.repository.findById());
    }
}
