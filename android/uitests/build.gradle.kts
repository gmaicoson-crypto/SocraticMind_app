plugins {
    id("com.android.test")
    alias(libs.plugins.kotlin.android)
}
android {
    namespace = "com.gmaicoson.socraticmind.uitests"
    compileSdk = 36
    targetProjectPath = ":app"
    experimentalProperties["android.experimental.self-instrumenting"] = true
    defaultConfig {
        minSdk = 26
        targetSdk = 36
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}
kotlin {
    jvmToolchain(21)
    compilerOptions.jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
}
dependencies {
    implementation(libs.test.runner)
    implementation(libs.test.junit)
    implementation(libs.uiautomator)
}
dependencyLocking {
    lockAllConfigurations()
}
