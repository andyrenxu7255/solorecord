package com.solorecord.storage;

import android.content.Context;
import android.content.SharedPreferences;

public final class SessionStore {
    private static final String PREFS = "solo_session";

    private final SharedPreferences preferences;

    public SessionStore(Context context) {
        this.preferences = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    public String getServerEndpoint() {
        return preferences.getString("serverEndpoint", "http://127.0.0.1:8000");
    }

    public void setServerEndpoint(String endpoint) {
        preferences.edit().putString("serverEndpoint", endpoint == null ? "" : endpoint.trim()).apply();
    }

    public String getToken() {
        return preferences.getString("token", "");
    }

    public String getDisplayName() {
        return preferences.getString("displayName", "");
    }

    public String getEmail() {
        return preferences.getString("email", "");
    }

    public void saveLogin(String token, String displayName, String email) {
        preferences.edit()
                .putString("token", token == null ? "" : token)
                .putString("displayName", displayName == null ? "" : displayName)
                .putString("email", email == null ? "" : email)
                .apply();
    }

    public void logout() {
        preferences.edit().remove("token").remove("displayName").remove("email").apply();
    }

    public boolean isLoggedIn() {
        return !getToken().isEmpty();
    }
}
