package com.solorecord.config;

import com.solorecord.BuildConfig;

public final class PreconfiguredConfig {
    private static final String COMPANY_SERVER_ENDPOINT = "https://record.uino.com";

    private PreconfiguredConfig() {
    }

    public static String serverEndpoint() {
        String buildEndpoint = BuildConfig.SERVER_ENDPOINT == null ? "" : BuildConfig.SERVER_ENDPOINT.trim();
        return buildEndpoint.isEmpty() ? COMPANY_SERVER_ENDPOINT : buildEndpoint;
    }
}
