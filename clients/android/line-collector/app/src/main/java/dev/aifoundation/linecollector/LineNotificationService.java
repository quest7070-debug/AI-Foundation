package dev.aifoundation.linecollector;

import android.app.Notification;
import android.os.Bundle;
import android.os.Parcelable;
import android.service.notification.NotificationListenerService;
import android.service.notification.StatusBarNotification;
import java.io.IOException;
import java.util.List;
import org.json.JSONObject;

public final class LineNotificationService extends NotificationListenerService {
    @Override public void onListenerConnected() {
        super.onListenerConnected();
        if (Journal.consent(this, "notification")) {
            save(Journal.coverage("notification", "LISTENER_CONNECTED"));
        }
    }

    @Override public void onListenerDisconnected() {
        if (Journal.consent(this, "notification")) {
            save(Journal.coverage("notification", "LISTENER_DISCONNECTED"));
        }
        super.onListenerDisconnected();
    }

    @Override public void onNotificationPosted(StatusBarNotification posted) {
        if (!Journal.consent(this, "notification") ||
            !Journal.LINE_PACKAGE.equals(posted.getPackageName())) return;
        Notification notification = posted.getNotification();
        if (notification == null) return;
        Bundle extras = notification.extras;
        if (extras == null) return;
        String title = text(extras.getCharSequence(Notification.EXTRA_CONVERSATION_TITLE));
        if (title.isEmpty()) title = text(extras.getCharSequence(Notification.EXTRA_TITLE));
        if (title.isEmpty()) title = "unresolved";
        String chat = "notify:" + title;
        Parcelable[] bundles = extras.getParcelableArray(Notification.EXTRA_MESSAGES);
        if (bundles != null && bundles.length > 0) {
            List<Notification.MessagingStyle.Message> messages =
                Notification.MessagingStyle.Message.getMessagesFromBundleArray(bundles);
            for (int i = 0; i < messages.size(); i++) {
                Notification.MessagingStyle.Message message = messages.get(i);
                if (message.getText() == null) continue;
                String body = text(message.getText());
                String sender = message.getSenderPerson() == null ? null
                    : text(message.getSenderPerson().getName());
                long stamp = message.getTimestamp() > 0 ? message.getTimestamp()
                    : posted.getPostTime();
                // A MessagingStyle sender is not proof of self attribution.
                String key = Journal.id(posted.getKey() + "|" + stamp + "|" + i
                    + "|" + body + "|" + sender);
                save(Journal.event("notification", "notice:" + key, chat,
                    sender, "incoming", body, stamp, "NOTIFICATION"));
            }
            return;
        }
        // Generic notifications may be a group summary, not a real individual message.
        String summary = text(extras.getCharSequence(Notification.EXTRA_TEXT));
        if (summary.isEmpty()) return;
        String key = Journal.id(posted.getKey() + "|" + posted.getPostTime()
            + "|" + summary + "|" + title);
        save(Journal.event("notification", "notice:" + key, chat, null,
            "unknown", summary, posted.getPostTime(), "NOTIFICATION_SUMMARY"));
    }

    private static String text(CharSequence value) {
        if (value == null) return "";
        String str = value.toString();
        return str.length() > 100_000 ? str.substring(0, 100_000) : str;
    }

    private void save(JSONObject json) {
        try {
            Journal.append(this, json);
        } catch (IOException error) {
            getSharedPreferences("owner_consent_v1", MODE_PRIVATE)
                .edit().putBoolean("capture_error", true).apply();
        }
    }
}
