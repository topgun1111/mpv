import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
}

// One VERSION file for PC and Android (repo root). versionCode formula = core `versionCode()`.
val versionText: String = rootProject.projectDir.resolve("../VERSION")
    .takeIf { it.isFile }?.readText()?.trim().orEmpty().ifEmpty { "0.0.0" }
val versionParts: List<Int> = versionText.split(".")
    .map { s -> s.takeWhile { it.isDigit() }.toIntOrNull() ?: 0 }
val computedVersionCode: Int = versionParts.getOrElse(0) { 0 } * 10000 +
    versionParts.getOrElse(1) { 0 } * 100 + versionParts.getOrElse(2) { 0 }

android {
    namespace = "com.takipli.oynat"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.takipli.oynat"
        minSdk = 29
        targetSdk = 36
        versionCode = computedVersionCode
        versionName = versionText
        ndk { abiFilters += "arm64-v8a" } // phone only (Snapdragon 8 Gen 3); no x86 emulator
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    // .onnx stays uncompressed: openFd() gives the size for the copy check and loading is faster.
    androidResources {
        noCompress += "onnx"
    }

    packaging {
        // QNN/HTP must load its skel libs from disk (ADSP_LIBRARY_PATH = nativeLibraryDir): extract the .so files.
        jniLibs.useLegacyPackaging = true
        jniLibs.pickFirsts += "**/libc++_shared.so" // ORT-QNN and OpenCV both ship it
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
    implementation(libs.androidx.compose.ui.tooling.preview)
    implementation(libs.kotlinx.coroutines.android)
    implementation(libs.opencv) // Part 8: LK optical flow for camera-motion compensation (arm64 only via abiFilters)
    implementation(libs.onnxruntime.android.qnn) // ORT with CPU + QNN (Hexagon HTP) providers; pulls com.qualcomm.qti:qnn-runtime
    debugImplementation(libs.androidx.compose.ui.tooling)
}
