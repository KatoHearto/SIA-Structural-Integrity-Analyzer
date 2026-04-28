package com.example.di;

public class EmailNotifier implements Notifier {
    public String deliver() {
        return "email";
    }
}
