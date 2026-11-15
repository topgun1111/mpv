import org.jetbrains.kotlin.gradle.dsl.JvmTarget

// Record-only variant ("Takipli Kayit"): play a clip, pinch-zoom + drag live, record the camera path, export it to MP4.
// Deliberately NOT part of :app: no pose / ONNX Runtime / QNN / OpenCV / tracking / scanning / updater / network.
// Shares only the pure-Kotlin :core module (view math, export math) and the same VERSION file.
plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
}

val versionText: String = rootProject.projectDir.resolve("../VERSION")
    .takeIf { it.isFile }?.readText()?.trim().orEmpty().ifEmpty { "0.0.0" }
val versionParts: List<Int> = versionText.split(".")
    .map { s -> s.takeWhile { it.isDigit() }.toIntOrNull() ?: 0 }
val buildNumber: Int = (System.getenv("BUILD_NUMBER") ?: "0").toIntOrNull()?.coerceIn(0, 999) ?: 0
val computedVersionCode: Int = (versionParts.getOrElse(0) { 0 } * 10000 +
    versionParts.getOrElse(1) { 0 } * 100 + versionParts.getOrElse(2) { 0 }) * 1000 + buildNumber

android {
    namespace = "com.takipli.oynat.rec"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.takipli.oynat.rec" // installs next to the full app (com.takipli.oynat[.sam])
        minSdk = 29
        targetSdk = 36
        versionCode = computedVersionCode
        versionName = versionText
        // No native libraries (Media3 is pure Java/Kotlin): no abiFilters, the APK runs on any phone ABI.
    }

    // Same committed key as :app, so the record app updates over itself between CI builds.
    val keystorePath: String? = System.getenv("KEYSTORE_PATH")
    signingConfigs {
        create("stable") {
            if (!keystorePath.isNullOrEmpty() && file(keystorePath).isFile) {
                storeFile = file(keystorePath)
                storePassword = System.getenv("KEYSTORE_PASSWORD")
                keyAlias = System.getenv("KEY_ALIAS")
                keyPassword = System.getenv("KEY_PASSWORD")
            } else {
                storeFile = file("../app/stable.jks")
                storePassword = "takipli-stable"
                keyAlias = "takipli"
                keyPassword = "takipli-stable"
            }
        }
    }

    buildTypes {
        debug { signingConfig = signingConfigs.getByName("stable") }
        release {
            isMinifyEnabled = false
            isShrinkResources = false
            signingConfig = signingConfigs.getByName("stable")
        }
    }

    lint {
        checkReleaseBuilds = false
        abortOnError = false
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    packaging {
        resources.excludes += "/META-INF/{AL2.0,LGPL2.1}"
    }
}

kotlin {
    compilerOptions {
        jvmTarget.set(JvmTarget.JVM_17)
    }
}

dependencies {
    implementation(project(":core"))
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.compose.foundation)
    implementation(libs.androidx.compose.material3)
    implementation(libs.androidx.compose.ui)
    implementation(libs.kotlinx.coroutines.android)
    implementation(libs.media3.exoplayer)   // preview player
    implementation(libs.media3.transformer) // export (hardware encoder, audio passthrough)
    implementation(libs.media3.effect)      // MatrixTransformation = the recorded camera path
}
