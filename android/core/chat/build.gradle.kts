plugins {
    alias(libs.plugins.kotlin.jvm)
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
    implementation(project(":core:storage"))
    implementation(project(":core:auth"))
    implementation(project(":core:network"))
    implementation(libs.serialization.json)
    implementation(libs.coroutines.core)
    implementation(libs.okhttp)
    constraints {
        implementation(libs.okio) {
            because("Use the same reviewed Okio version as core:network for URL parsing")
        }
    }
    implementation(libs.commonmark)
    implementation(libs.commonmark.tables)
    implementation(libs.commonmark.strikethrough)
    implementation(libs.commonmark.tasks)
    testImplementation(testFixtures(project(":core:network")))
    testImplementation(libs.junit.jupiter)
    testRuntimeOnly(libs.junit.launcher)
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
