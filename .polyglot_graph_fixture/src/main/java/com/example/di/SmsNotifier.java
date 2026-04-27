package com.example.di;

public class SmsNotifier implements Notifier {
    public String deliver() {
        return "sms";
    }
}
