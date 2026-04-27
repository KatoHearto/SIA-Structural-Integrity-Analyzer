package com.example.di;

import jakarta.inject.Named;

@Named("paypalGateway")
public class PaypalGateway implements PaymentGateway {
    public String fetch() {
        return "paypal";
    }
}
