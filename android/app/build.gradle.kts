plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.plugin.compose")
}

android {
    namespace = "app.onlyclaws.android"
    compileSdk = 37

    defaultConfig {
        applicationId = "app.onlyclaws.android"
        minSdk = 26
        targetSdk = 34
        versionCode = 7
        versionName = "0.7.0"
    }

    buildFeatures {
        compose = true
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("org.mozilla:rhino:1.7.15")
    implementation("androidx.a2ui.compose:compose-runtime:1.0.0-alpha01")
    implementation("androidx.a2ui.compose:compose-ui:1.0.0-alpha01")
    implementation("androidx.compose.material3:material3-a2ui:1.0.0-alpha01")
    implementation("androidx.compose.material3:material3:1.3.1")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.8.6")
    implementation("io.coil-kt:coil-compose:2.7.0")
    testImplementation("junit:junit:4.13.2")
    testImplementation("com.squareup.okhttp3:mockwebserver:4.12.0")
    testImplementation("com.squareup.okhttp3:okhttp-tls:4.12.0")
}
