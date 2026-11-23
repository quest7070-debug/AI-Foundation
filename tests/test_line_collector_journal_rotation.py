"""Run the real pure-Java journal logic against a tiny owner-private fixture.

Android Context/JSONObject are test-only stubs; no device, SDK, network, model,
owner messages or permissions are accessed. The limit is scaled down only in
the temporary compiled copy, exercising the same append/rotate/export code.
"""
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "clients/android/line-collector/app/src/main/java"
          / "dev/aifoundation/linecollector/Journal.java")


def _jdk_available():
    # macOS exposes /usr/bin/javac as a launcher even when no Java runtime
    # is installed. A PATH check is not evidence that compilation is possible.
    if not (shutil.which("javac") and shutil.which("java")):
        return False
    try:
        return all(subprocess.run(
            [binary, "-version"], capture_output=True, text=True,
            timeout=6, check=False).returncode == 0
            for binary in ("javac", "java"))
    except (OSError, subprocess.TimeoutExpired):
        return False


@pytest.mark.skipif(not _jdk_available(),
                    reason="working JDK unavailable; Android build acceptance remains separate")
def test_bounded_private_journal_rotation_and_snapshot(tmp_path):
    src = SOURCE.read_text(encoding="utf-8")
    assert "64L * 1024 * 1024" in src
    assert "MAX_SEALED_PARTS = 8" in src
    # A tiny test limit proves rotation and overflow without using hundreds of
    # MiB or requiring an emulator. Other production code is byte-for-byte.
    src = src.replace("64L * 1024 * 1024", "96L", 1)
    src = src.replace("MAX_SEALED_PARTS = 8", "MAX_SEALED_PARTS = 3", 1)

    def source(rel, text):
        path = tmp_path / "java" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    files = [
        source("dev/aifoundation/linecollector/Journal.java", src),
        source("android/content/SharedPreferences.java", """
package android.content;
public class SharedPreferences {
    public boolean getBoolean(String key, boolean otherwise) { return otherwise; }
    public Editor edit() { return new Editor(); }
    public static class Editor {
        public Editor putBoolean(String key, boolean value) { return this; }
        public void apply() {}
    }
}
"""),
        source("android/content/Context.java", """
package android.content;
import java.io.*;
public class Context {
    public static final int MODE_PRIVATE = 0;
    public static final int MODE_APPEND = 32768;
    private final File root;
    public Context(File root) { this.root = root; }
    public File getFilesDir() { return root; }
    public SharedPreferences getSharedPreferences(String n, int m) {
        return new SharedPreferences();
    }
    public FileOutputStream openFileOutput(String name, int mode) throws IOException {
        return new FileOutputStream(new File(root, name), true);
    }
}
"""),
        source("org/json/JSONObject.java", """
package org.json;
public class JSONObject {
    public static final Object NULL = new Object();
    private final String serialized;
    public JSONObject() { this("{}"); }
    public JSONObject(String value) { serialized = value; }
    public JSONObject put(String key, Object value) { return this; }
    public String toString() { return serialized; }
}
"""),
        source("dev/aifoundation/linecollector/JournalProbe.java", """
package dev.aifoundation.linecollector;
import android.content.Context;
import org.json.JSONObject;
import java.io.*;
import java.nio.charset.StandardCharsets;

public class JournalProbe {
    static void require(boolean yes) {
        if (!yes) throw new AssertionError("journal fixture failed");
    }
    public static void main(String[] args) throws Exception {
        File directory = new File(args[0]);
        require(directory.mkdirs());
        Context ctx = new Context(directory);
        for (int i = 0; i < 30; ++i) {
            Journal.append(ctx, new JSONObject("{\\"n\\":" + i + "}"));
        }
        require(Journal.sealedCount(ctx) >= 2);
        long originalBytes = Journal.totalBytes(ctx);
        class LateAppend extends ByteArrayOutputStream {
            boolean inserted = false;
            @Override public synchronized void write(byte[] b, int off, int len) {
                if (!inserted) {
                    inserted = true;
                    try {
                        Journal.append(ctx, new JSONObject("{\\"late\\":1}"));
                    } catch (IOException e) { throw new AssertionError(e); }
                }
                super.write(b, off, len);
            }
        }
        LateAppend out = new LateAppend();
        long copied = Journal.copySnapshot(ctx, out);
        String before = out.toString(StandardCharsets.UTF_8);
        require(copied == originalBytes);
        require(!before.contains("late"));
        require(before.contains("{\\"n\\":0}"));
        require(before.contains("{\\"n\\":29}"));
        require(before.lines().count() == 30L);
        ByteArrayOutputStream later = new ByteArrayOutputStream();
        Journal.copySnapshot(ctx, later);
        require(later.toString(StandardCharsets.UTF_8).contains("{\\"late\\":1}"));
        boolean full = false;
        for (int i = 30; i < 300; ++i) {
            try { Journal.append(ctx, new JSONObject("{\\"n\\":" + i + "}")); }
            catch (IOException expected) { full = true; break; }
        }
        require(full);
        long retained = Journal.totalBytes(ctx);
        require(retained >= originalBytes);
        ByteArrayOutputStream afterFull = new ByteArrayOutputStream();
        Journal.copySnapshot(ctx, afterFull);
        require(afterFull.size() == retained);
        require(afterFull.toString(StandardCharsets.UTF_8).contains("{\\"n\\":0}"));
        System.out.println("OWNER_JOURNAL_ROTATION_AND_FROZEN_EXPORT_OK");
    }
}
"""),
    ]
    classes = tmp_path / "classes"
    classes.mkdir()
    compiled = subprocess.run(
        ["javac", "-encoding", "UTF-8", "-d", str(classes),
         *[str(x) for x in files]], check=False,
        capture_output=True, text=True, timeout=40)
    # Synthetic stub/compiler diagnostics are safe to show when fixture
    # compilation fails; otherwise a CalledProcessError conceals the cause.
    assert compiled.returncode == 0, (
        "JOURNAL_JAVAC_FIXTURE_FAILED: " + compiled.stderr[-3500:])
    result = subprocess.run(["java", "-cp", str(classes),
                             "dev.aifoundation.linecollector.JournalProbe",
                             str(tmp_path / "private")], check=True,
                            capture_output=True, text=True, timeout=40)
    assert result.stdout.strip() == "OWNER_JOURNAL_ROTATION_AND_FROZEN_EXPORT_OK"
