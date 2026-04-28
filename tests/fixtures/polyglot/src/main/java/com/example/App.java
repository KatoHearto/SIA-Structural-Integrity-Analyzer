package com.example;

import com.example.service.UserService;

public class App extends BaseApp {
    private final UserService userService = new UserService();

    public String start() {
        return this.userService.loadUser();
    }
}
