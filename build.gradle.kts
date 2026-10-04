plugins {
    id("com.android.library") version "8.7.3" apply false
    kotlin("android") version "2.3.0" apply false
}

buildscript {
    repositories {
        google()
        mavenCentral()
        maven("https://jitpack.io")
    }
    dependencies {
        classpath("com.lagradost:cloudstream3-gradle:pre-release")
    }
}
