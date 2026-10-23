plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
}
android {
    namespace = "com.gmaicoson.socraticmind"
    compileSdk = 36
    defaultConfig {
        applicationId = "com.gmaicoson.socraticmind"
        minSdk = 26
        targetSdk = 36
        versionCode = 1
        versionName = "0.1.0-dev"
    }
    buildFeatures {
        compose = true
        buildConfig = true
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    buildTypes {
        debug {
            val address = providers.gradleProperty("socraticmind.apiUrl").getOrElse("http://10.0.2.2:8765/")
            require(address.none { it in "\"\\\r\n" }) { "Invalid API URL literal" }
            buildConfigField("String", "API_BASE_URL", "\"$address\"")
        }
        release {
            isMinifyEnabled = false
            val address = providers.gradleProperty("socraticmind.apiUrl").getOrElse("")
            require(address.none { it in "\"\\\r\n" }) { "Invalid API URL literal" }
            buildConfigField("String", "API_BASE_URL", "\"$address\"")
        }
    }
}
kotlin {
    jvmToolchain(21)
    compilerOptions.jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
}
dependencies {
    implementation(project(":core:auth"))
    implementation(project(":core:chat"))
    implementation(project(":core:network"))
    implementation(platform(libs.compose.bom))
    implementation(libs.compose.material3)
    implementation(libs.compose.ui)
    implementation(libs.activity.compose)
    implementation(libs.lifecycle.viewmodel)
    implementation(libs.lifecycle.runtime.compose)
    implementation(libs.coroutines.android)
}
dependencyLocking {
    lockAllConfigurations()
}
