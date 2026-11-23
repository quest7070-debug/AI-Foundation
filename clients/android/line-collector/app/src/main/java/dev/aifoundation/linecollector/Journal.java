package dev.aifoundation.linecollector;

import android.content.Context;
import org.json.JSONObject;
import java.io.File;
import java.io.FileOutputStream;
import java.io.FileInputStream;
import java.io.OutputStream;
import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Instant;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;

final class Journal {
    static final String LINE_PACKAGE = "jp.naver.line.android";
    private static final String PREF = "owner_consent_v1";
    private static final long MAX_FILE_BYTES = 64L * 1024 * 1024;
    // Bounded, owner-private local retention. Never delete unsent evidence.
    private static final int MAX_SEALED_PARTS = 8;
    private static final String FILE_NAME = "line-events.jsonl";

    private Journal() {}

    static boolean consent(Context context, String source) {
        return context.getSharedPreferences(PREF, Context.MODE_PRIVATE)
                .getBoolean(source, false);
    }

    static void setConsent(Context context, String source, boolean allowed) {
        context.getSharedPreferences(PREF, Context.MODE_PRIVATE)
                .edit().putBoolean(source, allowed).apply();
    }

    static File file(Context context) {
        return new File(context.getFilesDir(), FILE_NAME);
    }

    static String time(long millis) {
        return DateTimeFormatter.ISO_OFFSET_DATE_TIME.format(
                Instant.ofEpochMilli(millis).atZone(ZoneId.systemDefault()));
    }

    static String id(String value) {
        try {
            byte[] bytes = MessageDigest.getInstance("SHA-256").digest(
                    value.getBytes(StandardCharsets.UTF_8));
            StringBuilder hex = new StringBuilder();
            for (byte b : bytes) hex.append(String.format("%02x", b & 0xff));
            return hex.toString();
        } catch (Exception error) {
            throw new IllegalStateException(error);
        }
    }

    static JSONObject event(String source, String sourceId, String chat,
                            String actor, String direction, String text,
                            long eventMillis, String quality) {
        JSONObject json = new JSONObject();
        try {
            json.put("schema", "line-capture/v1");
            json.put("kind", "message");
            json.put("source", source);
            json.put("source_event_id", sourceId);
            json.put("conversation_key", chat);
            json.put("actor", actor == null ? JSONObject.NULL : actor);
            json.put("direction", direction);
            json.put("text", text);
            json.put("event_time", time(eventMillis));
            json.put("observed_at", time(System.currentTimeMillis()));
            json.put("quality", quality);
        } catch (Exception error) {
            throw new IllegalStateException(error);
        }
        return json;
    }

    static JSONObject coverage(String source, String reason) {
        JSONObject json = new JSONObject();
        long now = System.currentTimeMillis();
        try {
            json.put("schema", "line-capture/v1");
            json.put("kind", "coverage");
            json.put("source", source);
            json.put("source_event_id", source + ":" + reason + ":" + now);
            json.put("observed_at", time(now));
            json.put("quality", reason);
        } catch (Exception error) {
            throw new IllegalStateException(error);
        }
        return json;
    }

    private static File sealed(Context context, int number) {
        return new File(context.getFilesDir(),
            String.format(java.util.Locale.ROOT, "line-events-%04d.jsonl", number));
    }

    static synchronized long totalBytes(Context context) {
        long length = file(context).length();
        for (int i = 1; i <= MAX_SEALED_PARTS; i++) {
            length += sealed(context, i).length();
        }
        return length;
    }

    static synchronized int sealedCount(Context context) {
        int count = 0;
        for (int i = 1; i <= MAX_SEALED_PARTS; i++) {
            if (sealed(context, i).exists()) count++;
        }
        return count;
    }

    static synchronized void append(Context context, JSONObject event) throws IOException {
        File target = file(context);
        if (java.nio.file.Files.isSymbolicLink(target.toPath())) {
            throw new IOException("Untrusted private LINE journal path");
        }
        byte[] encoded = (event.toString() + "\n").getBytes(StandardCharsets.UTF_8);
        if (encoded.length > 256 * 1024) {
            throw new IOException("Oversized private LINE event");
        }
        if (target.length() + encoded.length > MAX_FILE_BYTES) {
            // This rename remains within Android's owner-private app directory.
            // It never overwrites, truncates, or deletes an older segment.
            int next = 1;
            while (next <= MAX_SEALED_PARTS
                    && java.nio.file.Files.exists(sealed(context, next).toPath(),
                        java.nio.file.LinkOption.NOFOLLOW_LINKS)) {
                next++;
            }
            if (next > MAX_SEALED_PARTS || !target.isFile()
                    || !target.renameTo(sealed(context, next))) {
                throw new IOException("Private LINE journal retention full; export required");
            }
        }
        try (FileOutputStream out = context.openFileOutput(FILE_NAME, Context.MODE_APPEND)) {
            out.write(encoded);
            out.getFD().sync();
        }
    }

    private static final class SnapshotPart {
        final FileInputStream input;
        final long bytes;
        SnapshotPart(FileInputStream input, long bytes) {
            this.input = input;
            this.bytes = bytes;
        }
    }

    private static void closeParts(List<SnapshotPart> parts) {
        for (SnapshotPart part : parts) {
            try { part.input.close(); } catch (IOException ignored) {}
        }
    }

    private static synchronized List<SnapshotPart> openSnapshot(Context context)
            throws IOException {
        // Open all FDs while holding the append lock. Even if the active
        // journal rotates immediately afterwards, its FD remains attached to
        // the same inode. The frozen byte lengths exclude later appends.
        ArrayList<SnapshotPart> parts = new ArrayList<>();
        try {
            for (int i = 1; i <= MAX_SEALED_PARTS + 1; i++) {
                File source = i <= MAX_SEALED_PARTS ? sealed(context, i) : file(context);
                if (java.nio.file.Files.isSymbolicLink(source.toPath())) {
                    throw new IOException("Untrusted private LINE segment link");
                }
                if (!source.exists()) continue;
                if (!source.isFile()) {
                    throw new IOException("Untrusted private LINE segment");
                }
                FileInputStream in = new FileInputStream(source);
                parts.add(new SnapshotPart(in, source.length()));
            }
            return parts;
        } catch (IOException failure) {
            closeParts(parts);
            throw failure;
        }
    }

    static long copySnapshot(Context context, OutputStream output) throws IOException {
        // Never delete on export: SAF providers may acknowledge a stream while
        // still buffering it. Imports are source-ID idempotent on replay.
        List<SnapshotPart> parts = openSnapshot(context);
        long written = 0;
        byte[] buffer = new byte[32 * 1024];
        try {
            for (SnapshotPart part : parts) {
                long remaining = part.bytes;
                while (remaining > 0) {
                    int n = part.input.read(buffer, 0,
                        (int) Math.min(buffer.length, remaining));
                    if (n <= 0) throw new IOException("Private LINE snapshot truncated");
                    output.write(buffer, 0, n);
                    written += n;
                    remaining -= n;
                }
            }
            output.flush();
            return written;
        } finally {
            closeParts(parts);
        }
    }
}
