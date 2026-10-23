plugins {
    alias(libs.plugins.kotlin.jvm)
    `java-test-fixtures`
}
kotlin {
    jvmToolchain(21)
    compilerOptions.jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
}
java {
    sourceCompatibility = JavaVersion.VERSION_17
    targetCompatibility = JavaVersion.VERSION_17
}
dependencies {
    implementation(libs.serialization.json)
    implementation(libs.okhttp)
    constraints {
        implementation(libs.okio) {
            because("Keep the reviewed Okio version while selecting the API 36 compatible OkHttp release")
        }
    }
    implementation(libs.coroutines.core)
    testImplementation(libs.junit.jupiter)
    testRuntimeOnly(libs.junit.launcher)
    testFixturesImplementation(libs.serialization.json)
}
tasks.test {
    useJUnitPlatform()
    systemProperty("socratic.contracts", rootProject.file("../contracts/fixtures").absolutePath)
    inputs
        .files(
            rootProject.fileTree("../contracts/fixtures") { include("*.json") },
            rootProject.fileTree("../scripts/contracts") { include("*_fixture.py") },
        ).withPathSensitivity(PathSensitivity.RELATIVE)
}
dependencyLocking {
    lockAllConfigurations()
}
