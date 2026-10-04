package com.darkneslord.tavsiyefilmtest

import com.lagradost.cloudstream3.*
import com.lagradost.cloudstream3.utils.ExtractorLink

/**
 * Eğitim amaçlı katalog örneği.
 * Arama, ana sayfa, kategori ve detay bilgilerini gösterir.
 * loadLinks bilinçli olarak boş bırakılmıştır: üçüncü taraf yayın/stream URL'si çıkarmaz.
 */
class TavsiyeFilmTest : MainAPI() {
    override var mainUrl = "https://tavsiyefilmizle.net"
    override var name = "TavsiyeFilm Test"
    override var lang = "tr"
    override val hasMainPage = true
    override val hasQuickSearch = true
    override val supportedTypes = setOf(TvType.Movie, TvType.TvSeries)

    override val mainPage = mainPageOf(
        "$mainUrl/" to "Editörün Önerileri",
        "$mainUrl/category/aksiyon-filmleri/" to "Aksiyon Filmleri",
        "$mainUrl/category/gerilim-filmleri/" to "Gerilim Filmleri",
        "$mainUrl/category/yerli-filmler/" to "Yerli Filmler",
        "$mainUrl/category/savas-filmleri/" to "Savaş Filmleri"
    )

    override suspend fun getMainPage(page: Int, request: MainPageRequest): HomePageResponse {
        val url = if (page <= 1) request.data else pageUrl(request.data, page)
        val document = app.get(url).document
        val results = document.select("a[href]").mapNotNull { element ->
            val href = fixUrlNull(element.attr("href")) ?: return@mapNotNull null
            val img = element.selectFirst("img")
            val title = element.selectFirst("h2,h3,h4,.title,.name")?.text()?.trim()
                ?: element.attr("title").trim()
                ?: return@mapNotNull null
            if (!isContentUrl(href) || title.length < 2) return@mapNotNull null
            val poster = fixUrlNull(img?.attr("data-src") ?: img?.attr("src"))
            toSearchResponse(title, href, poster)
        }.distinctBy { it.url }

        return newHomePageResponse(request.name, results, hasNext = results.isNotEmpty())
    }

    override suspend fun search(query: String): List<SearchResponse> {
        // Site tarafındaki arama yolu değişirse bu tek satır üzerinden güncellenebilir.
        val url = "$mainUrl/?s=${java.net.URLEncoder.encode(query, "UTF-8")}"
        val document = app.get(url).document
        return document.select("a[href]").mapNotNull { element ->
            val href = fixUrlNull(element.attr("href")) ?: return@mapNotNull null
            if (!isContentUrl(href)) return@mapNotNull null
            val title = element.selectFirst("h2,h3,h4,.title,.name")?.text()?.trim()
                ?: element.attr("title").trim()
            if (title.length < 2) return@mapNotNull null
            val img = element.selectFirst("img")
            toSearchResponse(title, href, fixUrlNull(img?.attr("data-src") ?: img?.attr("src")))
        }.distinctBy { it.url }
    }

    override suspend fun quickSearch(query: String): List<SearchResponse> = search(query)

    override suspend fun load(url: String): LoadResponse? {
        val document = app.get(url).document
        val title = document.selectFirst("h1")?.text()?.trim()
            ?: document.selectFirst("meta[property='og:title']")?.attr("content")?.trim()
            ?: return null

        val poster = fixUrlNull(
            document.selectFirst("meta[property='og:image']")?.attr("content")
                ?: document.selectFirst("img")?.attr("src")
        )

        val plot = document.selectFirst(".description, .summary, .film-description, [class*=description]")?.text()?.trim()
            ?: document.selectFirst("meta[name='description']")?.attr("content")?.trim()

        val year = Regex("\\b(19|20)\\d{2}\\b").find(document.text())?.value?.toIntOrNull()
        val rating = Regex("(?i)(?:IMDB|IMDb)\\s*(?:Puanı)?\\s*[:\\-]?\\s*(\\d+(?:[.,]\\d+)?)")
            .find(document.text())?.groupValues?.getOrNull(1)?.replace(',', '.')?.toDoubleOrNull()

        val isSeries = document.select("a[href*='/dizi/'], a[href*='/sezon/']").isNotEmpty() ||
            document.text().contains("Sezon", ignoreCase = true)

        return if (isSeries) {
            // Bu örnekte bölüm keşfi bilinçli olarak gösterim amaçlı bırakılmıştır.
            newTvSeriesLoadResponse(title, url, TvType.TvSeries, emptyList()) {
                this.posterUrl = poster
                this.year = year
                this.plot = plot
                this.tags = extractTags(document)
                this.score = rating?.let { Score.from10(it) }
            }
        } else {
            newMovieLoadResponse(title, url, TvType.Movie, url) {
                this.posterUrl = poster
                this.year = year
                this.plot = plot
                this.tags = extractTags(document)
                this.score = rating?.let { Score.from10(it) }
            }
        }
    }

    override suspend fun loadLinks(
        data: String,
        isCasting: Boolean,
        subtitleCallback: (SubtitleFile) -> Unit,
        callback: (ExtractorLink) -> Unit
    ): Boolean {
        // Bilerek yayın/stream URL'si çıkarılmıyor.
        return false
    }

    private fun toSearchResponse(title: String, url: String, poster: String?): SearchResponse {
        val normalized = title.replace(Regex("\\s+"), " ").trim()
        val year = Regex("\\b(19|20)\\d{2}\\b").find(normalized)?.value?.toIntOrNull()
        return newMovieSearchResponse(normalized, url, TvType.Movie) {
            posterUrl = poster
            this.year = year
        }
    }

    private fun extractTags(document: org.jsoup.nodes.Document): List<String> =
        document.select("a[href*='/category/']").map { it.text().trim() }
            .filter { it.isNotBlank() }
            .distinct()
            .take(12)

    private fun isContentUrl(url: String): Boolean =
        url.startsWith(mainUrl) && !url.contains("/category/") &&
            !url.contains("/tag/") && !url.contains("/page/") &&
            !url.endsWith("/category")

    private fun pageUrl(base: String, page: Int): String =
        if (base.endsWith("/")) "${base}page/$page/" else "$base/page/$page/"
}
