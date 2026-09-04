package com.signaldesk;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableScheduling;

@SpringBootApplication
@EnableScheduling
public class SignalDeskApplication {
    public static void main(String[] args) {
        SpringApplication.run(SignalDeskApplication.class, args);
    }
}
