package com.signaldesk;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;

class ToolchainTest {

    @Test
    void runsOnJdk21() {
        assertThat(Runtime.version().feature())
                .as("Homebrew Maven pulls JDK 26 and prefers it; Lombok and Spring "
                        + "plugins break on it. export JAVA_HOME=/opt/homebrew/opt/openjdk@21")
                .isEqualTo(21);
    }
}
