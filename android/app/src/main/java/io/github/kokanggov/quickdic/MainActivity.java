package io.github.kokanggov.quickdic;

import android.app.Activity;
import android.app.AlertDialog;
import android.os.Bundle;

/** 앱 목록에서 열었을 때: 사용법을 보여 주고, '사전 열기' 로 웹앱을 연다. */
public class MainActivity extends Activity {
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        new AlertDialog.Builder(this, android.R.style.Theme_DeviceDefault_Light_Dialog_Alert)
                .setTitle(R.string.help_title)
                .setMessage(R.string.help_body)
                .setPositiveButton(R.string.open_app, (d, w) -> WebLauncher.open(this, ""))
                .setNegativeButton(R.string.close, null)
                .setOnDismissListener(d -> finish())
                .show();
    }
}
