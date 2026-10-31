package io.github.kokanggov.quickdic;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;

/** 글자 선택 메뉴(또는 공유하기)에서 'QuickDic' 을 눌렀을 때: 고른 단어를 웹앱으로 넘기고 바로 닫힌다. */
public class LookupActivity extends Activity {
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        Intent in = getIntent();
        CharSequence text = null;
        if (in != null) {
            if (Intent.ACTION_PROCESS_TEXT.equals(in.getAction())) {
                text = in.getCharSequenceExtra(Intent.EXTRA_PROCESS_TEXT);
            } else if (Intent.ACTION_SEND.equals(in.getAction())) {
                text = in.getCharSequenceExtra(Intent.EXTRA_TEXT);
                if (text == null) text = in.getStringExtra(Intent.EXTRA_SUBJECT);
            }
        }
        WebLauncher.open(this, WebLauncher.clean(text));
        finish();
        overridePendingTransition(0, 0);
    }
}
