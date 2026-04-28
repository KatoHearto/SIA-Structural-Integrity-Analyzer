package com.example.di;

public class NotificationService {
    private final Notifier notifier;

    public NotificationService(Notifier notifier) {
        this.notifier = notifier;
    }

    public String send() {
        return this.notifier.deliver();
    }
}
