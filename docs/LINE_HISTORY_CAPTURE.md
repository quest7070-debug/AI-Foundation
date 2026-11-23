# Personal LINE history intake (owner-only)

Status: **IMPLEMENTATION IN DRAFT; NO LIVE ANDROID OR LINE ACCEPTANCE** (2026-11-11).
Source archive is independent from KLM's metadata database, because chat originals and
third-party conversations must not be silently promoted to HumanModel or Drive. Explicit
authorization to collect one's own LINE histories does not grant permission to publish,
summarize to external providers or use chat content as execution instructions.

## Sources and evidence levels

1. **Past history:** owner exports each LINE room as TXT via the official LINE UI.
   Import with explicit \`--chat\` stable ID and \`--self-name\` exact sender label;
   sender aliases must be supplied individually. The LINE standard Google Drive backup
   is for restoration, **not** a readable history API. TXT is user-supplied data,
   not cryptographically authenticated evidence.
2. **Future received:** opt-in Android NotificationListenerService captures only LINE
   notification contents visible to its permission; notifications may be suppressed,
   grouped, redacted, removed or unavailable. A notification never certifies outgoing.
3. **Future sent / visible received:** opt-in Android AccessibilityService reads only the
   foreground LINE view. Text may be input hints, controls, draft content, or
   misleading layout. Store only \`UNVERIFIED_UI_TEXT\` and at most
   \`outgoing_candidate\`, never treat this as an independently certified sent message.
4. **Reconciliation:** source event IDs deduplicate replays within one exact source.
   Cross-source similarity does not collapse two messages; same-minute identical
   messages can be distinct. No notification activity means **unknown coverage**,
   not proof of zero messages.

## Local intake

\`\`\`bash
# Source files must stay outside the Git repository and unshared cloud folders.
python scripts/line_history_import.py --db ~/.local/share/ai-foundation-private/line.db \\
  --owner me --txt /private/export/chat1.txt --chat chat-1 --self-name '自分'
python scripts/line_history_import.py --db ~/.local/share/ai-foundation-private/line.db \\
  --owner me --jsonl /private/export/line-events.jsonl
python -m pytest -q tests/test_line_history.py
\`\`\`

For many chat exports, prepare a private manifest next to the files so no
conversation identity is inferred from a duplicate display name or filename:

\`\`\`json
{"chats":[
  {"file":"chat-A.txt","conversation_key":"chat-001","self_names":["自分"]},
  {"file":"chat-B.txt","conversation_key":"chat-002","self_names":["自分"]}
]}
\`\`\`

\`\`\`bash
python scripts/line_history_import.py --db ~/.local/share/ai-foundation-private/line.db \
  --owner me --manifest /private/export/chats.json
\`\`\`

Manifest processing is incremental and replay-idempotent, not one giant
transaction; the file count and parse warnings must be reconciled against
the **user-supplied** chat-room inventory. This does not automatically obtain
historical files from LINE or prove that all chat rooms were exported.

Only aggregate counts print to stdout; never log payloads. Owner scopes require separate
databases, protected filesystem permissions and full-disk encryption. Existing data with
overly broad permissions fail closed. No raw content goes to GitHub, Drive, model providers,
KLM work.db or HumanModel. The \`klm_source_pointers()\` API returns *metadata only*;
caller must separately establish authenticated owner/scope and source reader before a
KLM job is approved. No auto-enqueue or network upload path is enabled by this change.

## Actual completeness boundary

Official export is per conversation. No documented personal-LINE API enumerates and
retrieves all historical personal conversations. Therefore \`account_complete=false\`
even when every provided file parses. Media files are *not* reconstructed from TXT
placeholders. UI visibility, notification permission gaps, identity and timestamp
mapping, unsent drafts, deleted messages and other-device sends are not recoverable
reliably. Preserve unknowns; never invent a zero-gap statement.

## Mobile acceptance / release checklist

- Confirm app-disclosed opt-in separately for notification and accessibility; permissions
  are off by default, and revocation stops collection.
- Observe incoming notification, foreground outgoing, multi-message notification update,
  mixed chat/group, repeated same-minute texts, edit draft, screenshot/UI label, reboot,
  revoked access, offline period, and 2-hour background run on the user's Android model.
- Export Android app JSONL to owner-private local store, import twice (second adds zero);
  reconcile against separately exported TXT across same bounded interval.
- Record explicit per-room coverage matrix with any gaps and wrong actor/room matches.
  No claim of production or complete coverage before these independent observations.
- Google Play AccessibilityService API publication has additional disclosure/declaration
  requirements; this is an owner-operated test client, not a release-ready Play app.

Official references:
- https://help.line.me/line/smartphone?contentId=20007388&lang=ja
- https://help.line.me/line/smartphone?contentId=20023473&lang=ja
- https://developer.android.com/reference/android/accessibilityservice/AccessibilityService
- https://support.google.com/googleplay/android-developer/answer/10964491?hl=ja
