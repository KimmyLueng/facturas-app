package com.example.gestionfacturas;

import android.os.Bundle;
import android.util.Log;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import androidx.appcompat.app.AppCompatActivity;

import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

/**
 * 启动内嵌的 Python（Chaquopy）+ Flask 服务，再用 WebView 打开本地界面。
 * 业务代码全部在 app/src/main/python/app 下，与桌面端共用同一套数据层。
 */
public class MainActivity extends AppCompatActivity {

    private static final String TAG = "GestionFacturas";
    private static final int PORT = 8080;
    private WebView web;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        if (!Python.isStarted()) {
            Python.start(new AndroidPlatform(this));
        }

        // 数据库与设置放在应用私有目录（/data/user/0/<pkg>/files）
        String dataDir = getFilesDir().getAbsolutePath();
        Python py = Python.getInstance();
        String url = py.getModule("main")
                .callAttr("start", dataDir, PORT)
                .toString();
        Log.i(TAG, "服务地址: " + url);

        web = new WebView(this);
        setContentView(web);

        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setLoadWithOverviewMode(true);
        s.setUseWideViewPort(true);
        s.setSupportZoom(true);
        s.setBuiltInZoomControls(true);
        s.setCacheMode(WebSettings.LOAD_NO_CACHE);

        web.setWebViewClient(new WebViewClient());      // 站内跳转仍用 WebView
        web.loadUrl(url);
    }

    @Override
    public void onBackPressed() {
        if (web != null && web.canGoBack()) {
            web.goBack();
        } else {
            super.onBackPressed();
        }
    }
}
