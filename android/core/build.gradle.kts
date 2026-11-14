import org.jetbrains.kotlin.gradle.dsl.JvmTarget

// Pure Kotlin module: no Android imports, so tests run on plain JVM (Linux CI).
plugins {
    alias(libs.plugins.kotlin.jvm)
    alias(libs.plugins.kotlin.serialization)
}

java {
    sourceCompatibility = JavaVersion.VERSION_17
    targetCompatibility = JavaVersion.VERSION_17
}

kotlin {
    compilerOptions {
        jvmTarget.set(JvmTarget.JVM_17)
    }
}

dependencies {
    implementation(libs.kotlinx.serialization.json)
    testImplementation(libs.kotlin.test)
}

tasks.test {
    useJUnit()
}
