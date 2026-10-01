package com.emix.gameroom; // Убедитесь, что ваш package name совпадает с тем, что вы ввели при создании проекта

import android.os.Build;
import android.view.View;
import android.view.WindowManager;
import android.os.Bundle;
import android.webkit.SslErrorHandler;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.webkit.WebResourceResponse;
import android.net.http.SslError;
import androidx.appcompat.app.AppCompatActivity;
import android.content.Intent;
import android.net.Uri;
import java.security.cert.X509Certificate;
import javax.net.ssl.HostnameVerifier;
import javax.net.ssl.HttpsURLConnection;
import javax.net.ssl.SSLContext;
import javax.net.ssl.SSLSession;
import javax.net.ssl.TrustManager;
import javax.net.ssl.X509TrustManager;
import java.util.HashMap;
import java.util.Map;
import android.webkit.CookieManager;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import androidx.core.splashscreen.SplashScreen;

public class MainActivity extends AppCompatActivity {

    private WebView webView;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        SplashScreen splashScreen = SplashScreen.installSplashScreen(this);
        super.onCreate(savedInstanceState);

        // Полноэкранный режим без статус-бара
        getWindow().setFlags(
                WindowManager.LayoutParams.FLAG_FULLSCREEN,
                WindowManager.LayoutParams.FLAG_FULLSCREEN
        );
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            getWindow().getAttributes().layoutInDisplayCutoutMode =
                    WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES;
        }
        View decorView = getWindow().getDecorView();
        decorView.setSystemUiVisibility(
                View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                        | View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                        | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
                        | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                        | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                        | View.SYSTEM_UI_FLAG_FULLSCREEN
        );

        setContentView(R.layout.activity_main);

        // Отключаем проверку SSL-сертификатов (для сертификатов Минцифры)
        trustAllCertificates();

        webView = findViewById(R.id.webView);
        // Делаем фон WebView черным с самого старта
        webView.setBackgroundColor(android.graphics.Color.parseColor("#08090d"));
        WebSettings webSettings = webView.getSettings();

        // 1. Включаем JavaScript
        webSettings.setJavaScriptEnabled(true);

        // 2. РАЗРЕШАЕМ ЗАПРОСЫ С FILE:// НА ВНЕШНИЕ РЕСУРСЫ (решает проблему CORS)
        webSettings.setAllowFileAccessFromFileURLs(true);
        webSettings.setAllowUniversalAccessFromFileURLs(true);

        // 3. Разрешаем смешанный контент (HTTP и HTTPS) - важно для API
        webSettings.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);

        // 4. Дополнительные настройки для производительности и хранения данных
        webSettings.setDomStorageEnabled(true);
        webSettings.setLoadWithOverviewMode(true);
        webSettings.setUseWideViewPort(true);
        webSettings.setCacheMode(WebSettings.LOAD_DEFAULT);
        // Разрешаем сторонние куки (нужно для YouTube)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
            CookieManager.getInstance().setAcceptThirdPartyCookies(webView, true);
        }

        // 5. Создаем WebViewClient, который игнорирует ошибки SSL и обрабатывает навигацию
        webView.setWebViewClient(new WebViewClient() {
            @Override
            public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
                String url = request.getUrl().toString();
                // Если это YouTube embed — открываем во внешнем приложении
                if (url.contains("youtube.com/embed/") || url.contains("youtu.be/")) {
                    Intent intent = new Intent(Intent.ACTION_VIEW, Uri.parse(url));
                    intent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                    startActivity(intent);
                    // Возвращаем пустой ответ, чтобы WebView не показывал ошибку
                    return new WebResourceResponse("text/plain", "UTF-8", null);
                }
                return super.shouldInterceptRequest(view, request);
            }

            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                String url = request.getUrl().toString();
                // Для всех остальных ссылок — загружаем внутри WebView
                Map<String, String> extraHeaders = new HashMap<>();
                extraHeaders.put("Referer", "https://" + getPackageName() + "/");
                view.loadUrl(url, extraHeaders);
                return true;
            }

            @Override
            public void onReceivedSslError(WebView view, SslErrorHandler handler, SslError error) {
                handler.proceed();
            }
        });

        webView.setWebChromeClient(new WebChromeClient());
        // Добавляем интерфейс для открытия YouTube в APK-версии
        webView.addJavascriptInterface(new Object() {
            @android.webkit.JavascriptInterface
            public void openYouTube(String videoId) {
                Intent intent = new Intent(Intent.ACTION_VIEW, Uri.parse("https://www.youtube.com/watch?v=" + videoId));
                intent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                startActivity(intent);
            }
            
            @android.webkit.JavascriptInterface
            public void exitApp() {
                MainActivity.this.finish();
                System.exit(0);
            }
        }, "AndroidInterface");
        // 6. Загружаем локальный HTML-файл из assets
        webView.loadUrl("file:///android_asset/GameRoom.html");
        
        // 7. Регистрация Service Worker для кэширования
        registerServiceWorker();
    }

    // Регистрация Service Worker
    private void registerServiceWorker() {
        try {
            if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.M) {
                // Регистрируем Service Worker через JavaScript
                String serviceWorkerPath = "file:///android_asset/service-worker.js";
                webView.evaluateJavascript(
                    "(function() { " +
                    "if ('serviceWorker' in navigator) { " +
                    "  navigator.serviceWorker.register(\"" + serviceWorkerPath + "\") " +
                    "    .then(function(registration) { " +
                    "      console.log(\"Service Worker registered: \" + registration.scope); " +
                    "    }) " +
                    "    .catch(function(error) { " +
                    "      console.log(\"Service Worker registration failed: \" + error); " +
                    "    }); " +
                    "} " +
                    "})()",
                    null
                );
            }
        } catch (Exception e) {
            e.printStackTrace();
        }
    }

    // Метод для отключения проверки SSL-сертификатов на уровне Java (для фоновых запросов)
    private void trustAllCertificates() {
        try {
            TrustManager[] trustAllCerts = new TrustManager[]{
                    new X509TrustManager() {
                        public X509Certificate[] getAcceptedIssuers() { return new X509Certificate[0]; }
                        public void checkClientTrusted(X509Certificate[] certs, String authType) {}
                        public void checkServerTrusted(X509Certificate[] certs, String authType) {}
                    }
            };
            SSLContext sc = SSLContext.getInstance("TLS");
            sc.init(null, trustAllCerts, new java.security.SecureRandom());
            HttpsURLConnection.setDefaultSSLSocketFactory(sc.getSocketFactory());
            HttpsURLConnection.setDefaultHostnameVerifier(new HostnameVerifier() {
                public boolean verify(String hostname, SSLSession session) { return true; }
            });
        } catch (Exception e) {
            e.printStackTrace();
        }
    }

    // Обработка кнопки "Назад" для навигации внутри WebView
    @Override
    public void onBackPressed() {
        if (webView.canGoBack()) {
            webView.goBack();
        } else {
            super.onBackPressed();
        }
    }
}