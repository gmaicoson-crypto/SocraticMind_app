pluginManagement {
    repositories {
        google {
            content {
                includeGroupByRegex("com\\.android.*")
                includeGroupByRegex("androidx\\..*")
                includeGroupByRegex("com\\.google\\.android.*")
                includeGroupByRegex("com\\.google\\.testing.*")
            }
        }
        mavenCentral()
        gradlePluginPortal()
    }
}
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google {
            content {
                includeGroupByRegex("com\\.android.*")
                includeGroupByRegex("androidx\\..*")
                includeGroupByRegex("com\\.google\\.android.*")
                includeGroupByRegex("com\\.google\\.testing.*")
            }
        }
        mavenCentral()
    }
}
rootProject.name = "SocraticMind"
include(":app", ":core:network", ":core:auth", ":core:chat", ":core:learning", ":core:storage", ":uitests")
