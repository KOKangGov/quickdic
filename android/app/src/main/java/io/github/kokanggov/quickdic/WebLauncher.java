package io.github.kokanggov.quickdic;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.content.pm.ResolveInfo;
import android.net.Uri;
import android.widget.Toast;

import java.util.List;

/** QuickDic 웹앱을 연다. 홈 화면에 설치된 웹앱(WebAPK)이 있으면 그것으로, 없으면 Chrome 으로. */
final class WebLauncher {
    private WebLauncher() {}

    /** 사전은 Chrome 저장소에 들어 있으므로, 다른 브라우저로 열면 사전이 없다고 나온다. 그래서 순서대로 찾는다. */
    private static final String[] BROWSERS = {
        "com.android.chrome", "com.chrome.beta", "com.chrome.dev", "com.chrome.canary",
    };

    static void open(Activity activity, String query) {
        Uri.Builder b = Uri.parse(BuildConfig.WEB_APP_URL).buildUpon();
        if (query != null && !query.isEmpty()) b.appendQueryParameter("text", query);
        Uri uri = b.build();

        Intent view = new Intent(Intent.ACTION_VIEW, uri);
        view.addCategory(Intent.CATEGORY_BROWSABLE);
        view.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);

        PackageManager pm = activity.getPackageManager();

        // 1) 홈 화면에 '설치'된 QuickDic 웹앱 (Chrome 이 만든 WebAPK)
        List<ResolveInfo> handlers = pm.queryIntentActivities(view, PackageManager.MATCH_ALL);
        for (ResolveInfo ri : handlers) {
            String pkg = ri.activityInfo.packageName;
            if (pkg.startsWith("org.chromium.webapk")) {
                if (tryStart(activity, new Intent(view).setPackage(pkg))) return;
            }
        }
        // 2) Chrome
        for (String pkg : BROWSERS) {
            if (isInstalled(pm, pkg) && tryStart(activity, new Intent(view).setPackage(pkg))) return;
        }
        // 3) 아무 브라우저
        if (tryStart(activity, view)) return;
        Toast.makeText(activity, R.string.no_browser, Toast.LENGTH_LONG).show();
    }

    private static boolean isInstalled(PackageManager pm, String pkg) {
        try {
            pm.getPackageInfo(pkg, 0);
            return true;
        } catch (PackageManager.NameNotFoundException e) {
            return false;
        }
    }

    private static boolean tryStart(Activity activity, Intent intent) {
        try {
            activity.startActivity(intent);
            return true;
        } catch (ActivityNotFoundException | SecurityException e) {
            return false;
        }
    }

    /** 고른 글에서 찾을 말만 남긴다: 첫 줄, 주소 빼기, 앞뒤 따옴표·문장부호 빼기, 너무 길면 자르기. */
    static String clean(CharSequence raw) {
        if (raw == null) return "";
        String s = raw.toString().replace(' ', ' ').trim();
        int nl = s.indexOf('\n');
        if (nl >= 0) s = s.substring(0, nl);
        s = s.replaceAll("https?://\\S+", " ").trim();
        s = s.replaceAll("^[\\p{Punct}\\p{Pi}\\p{Pf}\\p{Ps}\\p{Pe}“”‘’「」『』《》〈〉·…\\s]+", "");
        s = s.replaceAll("[\\p{Punct}\\p{Pi}\\p{Pf}\\p{Ps}\\p{Pe}“”‘’「」『』《》〈〉·…\\s]+$", "");
        s = s.replaceAll("\\s+", " ");
        if (s.length() > 80) s = s.substring(0, 80);
        return s;
    }
}
