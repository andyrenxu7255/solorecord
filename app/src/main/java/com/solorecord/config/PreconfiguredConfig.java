package com.solorecord.config;

import com.solorecord.BuildConfig;

public final class PreconfiguredConfig {
    private PreconfiguredConfig() {
    }

    public static String serverEndpoint() {
        return BuildConfig.SERVER_ENDPOINT == null ? "" : BuildConfig.SERVER_ENDPOINT.trim();
    }
}
