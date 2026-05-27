package com.solorecord.net;

public interface RecordCallback<T> {
    void onSuccess(T result);

    void onError(Exception exception);
}
