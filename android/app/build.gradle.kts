plugins {
    id("com.android.application")
}

android {
    namespace = "com.emix.gameroom"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.emix.gameroom"
        minSdk = 24
        targetSdk = 35
        versionCode = 1
        versionName = "1.0"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }

    // Отключаем компиляцию тестовых классов
    testOptions {
        unitTests.all { test ->
            test.enabled = false
        }
    }
}

// Исключаем тестовые файлы из компиляции
tasks.withType(JavaCompile::class) {
    exclude("**/ExampleUnitTest.java")
    exclude("**/ExampleInstrumentedTest.java")
}

dependencies {
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("com.google.android.material:material:1.12.0")
    implementation("androidx.constraintlayout:constraintlayout:2.2.0")
    implementation("androidx.core:core-splashscreen:1.0.1")
}