plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.plugin.compose")
}

android {
    namespace = "app.onlyclaws.android"
    compileSdk = 37
    ndkVersion = "29.0.14206865"

    defaultConfig {
        applicationId = "app.onlyclaws.android"
        minSdk = 26
        targetSdk = 34
        versionCode = 33
        versionName = "0.8.25"
        ndk { abiFilters += "arm64-v8a" }
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

// Not on Maven; fetched once from the sherpa-onnx release into app/libs (git-ignored).
val sherpaAar = file("libs/sherpa-onnx-2.0.1.aar")
if (!sherpaAar.isFile) {
    sherpaAar.parentFile.mkdirs()
    val part = File(sherpaAar.path + ".part")
    uri("https://github.com/k2-fsa/sherpa-onnx/releases/download/v2.0.1/sherpa-onnx-2.0.1.aar")
        .toURL().openStream().use { input -> part.outputStream().use { input.copyTo(it) } }
    part.renameTo(sherpaAar)
}

dependencies {
    implementation(files(sherpaAar))
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("com.hierynomus:sshj:0.39.0")
    implementation("org.slf4j:slf4j-nop:2.0.16")
    implementation("com.caoccao.javet:javet-v8-android:6.0.2")
    implementation("androidx.compose.material3:material3:1.3.1")
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20240303")
    testImplementation("com.caoccao.javet:javet:6.0.2")
    testImplementation("com.caoccao.javet:javet-v8-macos-arm64:6.0.2")
    testImplementation("com.squareup.okhttp3:mockwebserver:4.12.0")
    testImplementation("org.apache.sshd:sshd-core:2.13.2")
    testImplementation("org.apache.sshd:sshd-common:2.13.2")
    testImplementation("com.squareup.okhttp3:okhttp-tls:4.12.0")
}
