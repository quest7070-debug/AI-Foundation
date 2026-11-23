package dev.aifoundation.linecollector;

import android.accessibilityservice.AccessibilityService;
import android.graphics.Rect;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;
import java.io.IOException;
import java.util.ArrayDeque;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.Map;
import org.json.JSONObject;

public final class LineScreenService extends AccessibilityService {
    private final Map<String, Boolean> recent = new LinkedHashMap<String, Boolean>() {
        @Override protected boolean removeEldestEntry(Map.Entry<String, Boolean> entry) {
            return size() > 800;
        }
    };

    @Override public void onAccessibilityEvent(AccessibilityEvent event) {
        if (!Journal.consent(this, "screen") || event.getPackageName() == null ||
            !Journal.LINE_PACKAGE.contentEquals(event.getPackageName())) return;
        int type = event.getEventType();
        if (type != AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED &&
            type != AccessibilityEvent.TYPE_WINDOW_CONTENT_CHANGED &&
            type != AccessibilityEvent.TYPE_VIEW_SCROLLED) return;
        AccessibilityNodeInfo root = getRootInActiveWindow();
        if (root == null) return;
        // These are candidates, not certified sent messages or even certified chat bodies.
        int width = getResources().getDisplayMetrics().widthPixels;
        ArrayDeque<AccessibilityNodeInfo> queue = new ArrayDeque<>();
        queue.add(root);
        int visited = 0, emitted = 0;
        long now = System.currentTimeMillis();
        while (!queue.isEmpty() && visited++ < 500 && emitted < 50) {
            AccessibilityNodeInfo node = queue.removeFirst();
            try {
                CharSequence clazz = node.getClassName();
                String className = clazz == null ? "" : clazz.toString();
                CharSequence raw = node.getText();
                if (!node.isEditable() && !node.isPassword()
                    && !className.contains("EditText")
                    && !className.contains("Button") && raw != null) {
                    String value = raw.toString().trim();
                    Rect rect = new Rect();
                    node.getBoundsInScreen(rect);
                    if (value.length() >= 2 && value.length() <= 2000 && rect.width() > 0
                        && rect.width() < width * 0.90f) {
                        String side = rect.left > width * 0.52f
                            ? "outgoing_candidate" : "unknown";
                        // Positional hints can misclassify menus; never set 'outgoing'.
                        String key = "ui:" + Journal.id(value + "|" + rect.left + "|"
                            + rect.top + "|" + (now / 30_000));
                        if (!recent.containsKey(key)) {
                            recent.put(key, true);
                            save(Journal.event("screen", key, "screen:unresolved",
                                null, side, value, now, "UNVERIFIED_UI_TEXT"));
                            emitted++;
                        }
                    }
                }
                for (int i = 0; i < node.getChildCount() && queue.size() < 500; i++) {
                    AccessibilityNodeInfo child = node.getChild(i);
                    if (child != null) queue.addLast(child);
                }
            } finally {
                node.recycle();
            }
        }
    }

    @Override public void onInterrupt() {
        if (Journal.consent(this, "screen")) {
            save(Journal.coverage("screen", "SCREEN_DISABLED"));
        }
    }

    @Override protected void onServiceConnected() {
        super.onServiceConnected();
        if (Journal.consent(this, "screen")) {
            save(Journal.coverage("screen", "SCREEN_ENABLED"));
        }
    }

    private void save(JSONObject event) {
        try {
            Journal.append(this, event);
        } catch (IOException error) {
            getSharedPreferences("owner_consent_v1", MODE_PRIVATE)
                .edit().putBoolean("capture_error", true).apply();
        }
    }
}
