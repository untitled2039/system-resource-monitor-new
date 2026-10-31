plugins {
    id("com.android.application")
}

android {
    namespace = "org.systemresmonitor.agent"
    compileSdk = 35

    defaultConfig {
        applicationId = "org.systemresmonitor.agent"
        minSdk = 26
        targetSdk = 35
        versionCode = 4
        versionName = "3.1.0"
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

dependencies {
    implementation("androidx.activity:activity-ktx:1.9.3")
    // Shizuku: run shell-level commands to read real CPU usage and all processes.
    implementation("dev.rikka.shizuku:api:13.1.5")
    implementation("dev.rikka.shizuku:provider:13.1.5")
}
