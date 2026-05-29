package com.solorecord.net;

import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.Map;

public final class HttpJsonClient {
    private static final int TIMEOUT_MILLIS = 60_000;
    private static final int STREAM_BUFFER_BYTES = 64 * 1024;

    public JSONObject postJson(String endpoint, String apiKey, JSONObject body) throws IOException {
        if (endpoint == null || endpoint.trim().isEmpty()) {
            throw new IOException("接口地址未配置");
        }
        HttpURLConnection connection = null;
        try {
            connection = (HttpURLConnection) new URL(endpoint.trim()).openConnection();
            connection.setRequestMethod("POST");
            connection.setConnectTimeout(TIMEOUT_MILLIS);
            connection.setReadTimeout(TIMEOUT_MILLIS);
            connection.setDoOutput(true);
            connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
            if (apiKey != null && !apiKey.trim().isEmpty()) {
                connection.setRequestProperty("Authorization", "Bearer " + apiKey.trim());
            }

            byte[] payload = body.toString().getBytes(StandardCharsets.UTF_8);
            connection.setFixedLengthStreamingMode(payload.length);
            try (OutputStream output = connection.getOutputStream()) {
                output.write(payload);
            }

            int code = connection.getResponseCode();
            String response = readResponse(code >= 400 ? connection.getErrorStream() : connection.getInputStream());
            if (code >= 400) {
                throw new IOException("HTTP " + code + ": " + response);
            }
            return new JSONObject(response);
        } catch (Exception exception) {
            if (exception instanceof IOException) {
                throw (IOException) exception;
            }
            throw new IOException("请求失败", exception);
        } finally {
            if (connection != null) {
                connection.disconnect();
            }
        }
    }

    public JSONObject getJson(String endpoint, String apiKey) throws IOException {
        if (endpoint == null || endpoint.trim().isEmpty()) {
            throw new IOException("接口地址未配置");
        }
        HttpURLConnection connection = null;
        try {
            connection = (HttpURLConnection) new URL(endpoint.trim()).openConnection();
            connection.setRequestMethod("GET");
            connection.setConnectTimeout(TIMEOUT_MILLIS);
            connection.setReadTimeout(TIMEOUT_MILLIS);
            if (apiKey != null && !apiKey.trim().isEmpty()) {
                connection.setRequestProperty("Authorization", "Bearer " + apiKey.trim());
            }

            int code = connection.getResponseCode();
            String response = readResponse(code >= 400 ? connection.getErrorStream() : connection.getInputStream());
            if (code >= 400) {
                throw new IOException("HTTP " + code + ": " + response);
            }
            return new JSONObject(response);
        } catch (Exception exception) {
            if (exception instanceof IOException) {
                throw (IOException) exception;
            }
            throw new IOException("请求失败", exception);
        } finally {
            if (connection != null) {
                connection.disconnect();
            }
        }
    }

    public byte[] getBytes(String endpoint, String apiKey) throws IOException {
        if (endpoint == null || endpoint.trim().isEmpty()) {
            throw new IOException("接口地址未配置");
        }
        HttpURLConnection connection = null;
        try {
            connection = (HttpURLConnection) new URL(endpoint.trim()).openConnection();
            connection.setRequestMethod("GET");
            connection.setConnectTimeout(TIMEOUT_MILLIS);
            connection.setReadTimeout(TIMEOUT_MILLIS);
            if (apiKey != null && !apiKey.trim().isEmpty()) {
                connection.setRequestProperty("Authorization", "Bearer " + apiKey.trim());
            }

            int code = connection.getResponseCode();
            if (code >= 400) {
                String response = readResponse(connection.getErrorStream());
                throw new IOException("HTTP " + code + ": " + response);
            }
            return readBytes(connection.getInputStream());
        } catch (Exception exception) {
            if (exception instanceof IOException) {
                throw (IOException) exception;
            }
            throw new IOException("请求失败", exception);
        } finally {
            if (connection != null) {
                connection.disconnect();
            }
        }
    }

    public JSONObject postMultipartFile(
            String endpoint,
            String apiKey,
            Map<String, String> fields,
            String fileField,
            File file,
            String mimeType) throws IOException {
        if (endpoint == null || endpoint.trim().isEmpty()) {
            throw new IOException("接口地址未配置");
        }
        if (file == null || !file.exists()) {
            throw new IOException("上传文件不存在");
        }
        String boundary = "SoloRecordBoundary" + System.currentTimeMillis();
        HttpURLConnection connection = null;
        try {
            connection = (HttpURLConnection) new URL(endpoint.trim()).openConnection();
            connection.setRequestMethod("POST");
            connection.setConnectTimeout(TIMEOUT_MILLIS);
            connection.setReadTimeout(TIMEOUT_MILLIS);
            connection.setDoOutput(true);
            connection.setChunkedStreamingMode(STREAM_BUFFER_BYTES);
            connection.setRequestProperty("Content-Type", "multipart/form-data; boundary=" + boundary);
            if (apiKey != null && !apiKey.trim().isEmpty()) {
                connection.setRequestProperty("Authorization", "Bearer " + apiKey.trim());
            }

            try (OutputStream output = connection.getOutputStream()) {
                for (Map.Entry<String, String> entry : fields.entrySet()) {
                    writeUtf8(output, "--" + boundary + "\r\n");
                    writeUtf8(output, "Content-Disposition: form-data; name=\"" + escape(entry.getKey()) + "\"\r\n\r\n");
                    writeUtf8(output, entry.getValue() == null ? "" : entry.getValue());
                    writeUtf8(output, "\r\n");
                }

                writeUtf8(output, "--" + boundary + "\r\n");
                writeUtf8(output, "Content-Disposition: form-data; name=\"" + escape(fileField)
                        + "\"; filename=\"" + escape(file.getName()) + "\"\r\n");
                writeUtf8(output, "Content-Type: " + (mimeType == null || mimeType.isEmpty() ? "application/octet-stream" : mimeType) + "\r\n\r\n");
                try (FileInputStream input = new FileInputStream(file)) {
                    byte[] buffer = new byte[STREAM_BUFFER_BYTES];
                    int read;
                    while ((read = input.read(buffer)) >= 0) {
                        output.write(buffer, 0, read);
                    }
                }
                writeUtf8(output, "\r\n--" + boundary + "--\r\n");
            }

            int code = connection.getResponseCode();
            String response = readResponse(code >= 400 ? connection.getErrorStream() : connection.getInputStream());
            if (code >= 400) {
                throw new IOException("HTTP " + code + ": " + response);
            }
            return new JSONObject(response);
        } catch (Exception exception) {
            if (exception instanceof IOException) {
                throw (IOException) exception;
            }
            throw new IOException("请求失败", exception);
        } finally {
            if (connection != null) {
                connection.disconnect();
            }
        }
    }

    private static String readResponse(InputStream stream) throws IOException {
        if (stream == null) {
            return "";
        }
        StringBuilder builder = new StringBuilder();
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(stream, StandardCharsets.UTF_8))) {
            String line;
            while ((line = reader.readLine()) != null) {
                builder.append(line).append('\n');
            }
        }
        return builder.toString().trim();
    }

    private static byte[] readBytes(InputStream stream) throws IOException {
        if (stream == null) {
            return new byte[0];
        }
        byte[] buffer = new byte[1024 * 64];
        java.io.ByteArrayOutputStream output = new java.io.ByteArrayOutputStream();
        int read;
        while ((read = stream.read(buffer)) >= 0) {
            output.write(buffer, 0, read);
        }
        return output.toByteArray();
    }

    private static void writeUtf8(OutputStream output, String value) throws IOException {
        output.write(value.getBytes(StandardCharsets.UTF_8));
    }

    private static String escape(String value) {
        return value == null ? "" : value.replace("\\", "\\\\").replace("\"", "\\\"");
    }
}
