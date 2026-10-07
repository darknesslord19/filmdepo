plugins {
    id("com.android.library")
    kotlin("android")
}

version = 1

cloudstream {
    description = "TavsiyeFilmTest — katalog/arama/detay örneği. Oynatma bağlantısı çıkarmaz."
    authors = listOf("Darknes Lord")
    status = 1
    tvTypes = listOf("Movie", "TvSeries")
    language = "tr"
    iconUrl = "https://tavsiyefilmizle.net/favicon.ico"
}

dependencies {
    implementation("com.lagradost:cloudstream3:pre-release")
}
