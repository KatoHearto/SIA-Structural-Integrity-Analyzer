package com.example.service;

import com.example.repo.UserRepository;

public class UserService {
    private final UserRepository repository = new UserRepository();

    public String loadUser() {
        return this.repository.findById();
    }
}
