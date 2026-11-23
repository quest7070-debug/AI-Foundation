package dev.aifoundation.linecollector;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.os.Bundle;
import android.provider.Settings;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;
import java.io.OutputStream;

public final class MainActivity extends Activity {
    private static final int EXPORT = 41;
    private TextView status;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        layout.setPadding(32, 32, 32, 32);
        TextView disclosure = new TextView(this);
        disclosure.setText("個人用LINEライフログ。通知は受信文を、画面取得はLINE表示中の文章と送信候補を保存します。"
            + "他人の発言を含みます。画面情報は送信済みの証明ではありません。"
            + "端末内だけに保存し、ネット送信・自動送信・AI利用はしません。"
            + "各権限とアプリ内の記録を個別に停止できます。");
        layout.addView(disclosure);
        status = new TextView(this);
        layout.addView(status);
        button(layout, "LINE通知の取得を設定", () -> consentDialog("notification",
            "LINEの通知メッセージ本文・送信者表示名を収集します。通知以外は取得できません。",
            Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS));
        button(layout, "LINE画面の取得を設定", () -> consentDialog("screen",
            "前面表示中のLINE画面から文章を候補として記録します。他人の会話、操作ラベル、下書きも"
            + "誤って含まれる可能性があります。利用するには明示同意が必要です。",
            Settings.ACTION_ACCESSIBILITY_SETTINGS));
        button(layout, "記録をファイル出力（端末外へ自動送信しない）", this::export);
        setContentView(layout);
        refresh();
    }

    private void button(LinearLayout layout, String label, Runnable onClick) {
        Button button = new Button(this);
        button.setText(label);
        button.setOnClickListener(v -> onClick.run());
        layout.addView(button);
    }

    private void consentDialog(String source, String description, String settingsAction) {
        new AlertDialog.Builder(this).setTitle("LINE記録の明示同意")
            .setMessage(description + "\n機能を使うにはAndroidの権限画面でも許可してください。")
            .setPositiveButton("同意して権限画面を開く", (d, w) -> {
                Journal.setConsent(this, source, true);
                try {
                    startActivity(new Intent(settingsAction));
                } catch (Exception e) {
                    Journal.setConsent(this, source, false);
                }
                refresh();
            })
            .setNeutralButton("収集停止", (d, w) -> {
                Journal.setConsent(this, source, false);
                refresh();
            })
            .setNegativeButton("キャンセル", (d, w) -> {})
            .show();
    }

    private void export() {
        Intent i = new Intent(Intent.ACTION_CREATE_DOCUMENT);
        i.addCategory(Intent.CATEGORY_OPENABLE);
        i.setType("application/x-ndjson");
        i.putExtra(Intent.EXTRA_TITLE, "line-events.jsonl");
        startActivityForResult(i, EXPORT);
    }

    @Override protected void onActivityResult(int code, int resultCode, Intent data) {
        super.onActivityResult(code, resultCode, data);
        if (code != EXPORT || resultCode != RESULT_OK || data == null || data.getData() == null)
            return;
        final android.net.Uri destination = data.getData();
        status.setText("スナップショットをファイル出力中。記録は継続します。");
        // No UI-thread large file copy. Journal freezes exact FD lengths,
        // allowing listener/screen append and rotation while copying.
        new Thread(() -> {
            try (OutputStream out = getContentResolver().openOutputStream(destination)) {
                if (out == null) throw new IllegalStateException("No output stream");
                long bytes = Journal.copySnapshot(getApplicationContext(), out);
                runOnUiThread(() -> status.setText(
                    "エクスポート書込完了（" + bytes + " bytes）。端末内原本は保持。"
                    + "保存先の永続化・全会話取得は未検証です。"));
            } catch (Exception error) {
                runOnUiThread(() -> status.setText(
                    "エクスポート失敗。端末内の全記録を保持しています。"));
            }
        }, "line-owner-export").start();
    }

    @Override protected void onResume() {
        super.onResume();
        refresh();
    }

    private void refresh() {
        if (status == null) return;
        status.setText("通知：" + (Journal.consent(this, "notification") ? "アプリ内同意済" : "停止")
            + " 画面：" + (Journal.consent(this, "screen") ? "アプリ内同意済" : "停止")
            + "\n端末内の総保存量：" + Journal.totalBytes(this) + " bytes"
            + "（確定済みセグメント：" + Journal.sealedCount(this) + "/8）"
            + "\n書込エラー：" + (getSharedPreferences("owner_consent_v1", MODE_PRIVATE).getBoolean("capture_error", false) ? "あり（収集漏れの可能性）" : "記録なし")
            + "\n※Android側の権限状態は設定画面で別途確認してください。");
    }
}
