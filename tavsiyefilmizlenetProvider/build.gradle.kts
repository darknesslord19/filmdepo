plugins {
    id("com.android.library")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.v81.generated.tavsiyefilmizlenet"
    compileSdk = 35

    defaultConfig {
        minSdk = 23
    }
}

dependencies {
    compileOnly("com.lagradost:cloudstream3:pre-release")
}
