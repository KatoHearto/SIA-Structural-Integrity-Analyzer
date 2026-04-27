package com.example.di;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Qualifier;

public class QualifiedBillingService {
    @Autowired
    @Qualifier("paypalGateway")
    private PaymentGateway gateway;

    public String charge() {
        return this.gateway.fetch();
    }
}
