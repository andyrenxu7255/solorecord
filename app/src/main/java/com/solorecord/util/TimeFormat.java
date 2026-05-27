package com.solorecord.util;

import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;

public final class TimeFormat {
    private static final ThreadLocal<SimpleDateFormat> DISPLAY_FORMAT =
            ThreadLocal.withInitial(() -> new SimpleDateFormat("yyyy-MM-dd HH:mm", Locale.CHINA));
    private static final ThreadLocal<SimpleDateFormat> FILE_FORMAT =
            ThreadLocal.withInitial(() -> new SimpleDateFormat("yyyyMMdd_HHmmss", Locale.CHINA));

    private TimeFormat() {
    }

    public static String display(long millis) {
        return DISPLAY_FORMAT.get().format(new Date(millis));
    }

    public static String filenameNow() {
        return FILE_FORMAT.get().format(new Date());
    }
}
