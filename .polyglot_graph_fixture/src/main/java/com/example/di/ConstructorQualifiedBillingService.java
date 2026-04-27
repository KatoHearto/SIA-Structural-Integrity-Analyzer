package com.example.di;

import jakarta.inject.Inject;
import org.springframework.beans.factory.annotation.Qualifier;

public class ConstructorQualifiedBillingService {
    private final PaymentGateway gateway;

    @Inject
    public ConstructorQualifiedBillingService(@Qualifier("paypalGateway") PaymentGateway gateway) {
        this.gateway = gateway;
    }

    public String charge() {
        return this.gateway.fetch();
    }
}
