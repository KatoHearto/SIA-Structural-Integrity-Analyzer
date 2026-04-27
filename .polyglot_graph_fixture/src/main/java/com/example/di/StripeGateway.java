package com.example.di;

import org.springframework.context.annotation.Primary;
import org.springframework.stereotype.Service;

@Service
@Primary
public class StripeGateway implements PaymentGateway {
    public String fetch() {
        return "stripe";
    }
}
