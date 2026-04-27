package com.example.di;

public class BillingService {
    private final PaymentGateway gateway;

    public BillingService(PaymentGateway gateway) {
        this.gateway = gateway;
    }

    public String charge() {
        return this.gateway.fetch();
    }
}
