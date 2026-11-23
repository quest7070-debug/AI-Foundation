# Android LINE capture test client

**Not accepted on a real device and not production-ready.** The only supported
purpose of this owner-side client is to observe *your own visible LINE data*.
No root, ADB, unofficial LINE login, accessibility gestures, network permissions,
messaging API, write actions or external uploads. No additional LLM/service.

The source app package is \`jp.naver.line.android\`. Adjust only after verifying
the official LINE package on the actual device. The test client targets API 30+
and Android SDK 35 with Android Gradle Plugin 8.7.3 / JDK 17.
Open \`clients/android/line-collector\` in Android Studio and build a debug APK.
No signed artifact, preinstalled Android SDK, Gradle wrapper binary or real-device
acceptance is claimed here.

After installation:
1. Open the collector app. Read its disclosure and separately grant consent for
   *notification* and (if desired) *screen* capture. Then independently enable
   each service in Android Settings. Both are disabled in app preferences by default.
2. Use LINE normally. Only notifications and LINE UI text *observed while visible*
   become local records. UI text is unverified; \`outgoing_candidate\` is not a
   certified sent message. Editors are skipped, but other controls or previews
   can still be misclassified. Notification updates may include summaries.
3. Use the explicit **export** action to save \`line-events.jsonl\` into an owner-
   controlled location; copy it to a private PC path and run
   \`python scripts/line_history_import.py --db ... --owner ... --jsonl ...\`.
   Captures now rotate into **up to eight additional private 64 MiB parts**
   without overwriting older messages. Export captures an ordered,
   exact-byte-length snapshot of all sealed parts plus the active journal while
   collection continues; subsequent events appear in the next export.
   The original files are **never deleted automatically**, even after SAF
   output is acknowledged. Importing overlapping exports remains idempotent
   by source event ID. The limit still stops capture when storage fills.

4. Export individual historical chats from LINE as TXT separately and import
   them with \`--txt --chat --self-name\`. Import the same file twice to verify
   source-idempotency. No automatic cross-source proof of complete capture.
   For many historical TXT chats, use `--manifest` with explicit room keys and
   sender aliases. The importer streams one file at a time through a single
   local SQLite transaction: a later malformed/missing export rolls back all
   batch inserts. Replaying identical exports remains idempotent, including
   owner-sent messages. Paths must stay beneath the manifest directory.
   This does not establish complete account-wide history.
5. Revoke either Android permission and/or the matching in-app consent to stop
   the service. Uninstalling the test client removes its own private log.

Caveats: Other-device messages, muted notifications, missing content, redacted
notifications, edits/deletions, old unseen messages and screen-off outgoing are
unavailable. Screen chat identification is deliberately unresolved; never use
it as a canonical sender or room. Each private journal part is bounded at 64 MiB, and up to eight sealed
parts plus the active file are retained. When owner-only storage fills, capture
stops and the existing capture-error flag is set. An SAF export does not
certify that a third-party destination durably kept the data. This is not
complete continuous backup until owner-verified retention pruning/private
sync, room attribution and native device acceptance are implemented.
Do not put real exported chats into Git, Actions artifacts, or test fixtures.
