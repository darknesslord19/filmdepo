package com.tavsiyefilmizle

import android.util.Base64
import com.lagradost.cloudstream3.*
import com.lagradost.cloudstream3.utils.*
import org.json.JSONObject
import org.jsoup.nodes.Element
import java.net.URI
import java.net.URLEncoder
import java.security.MessageDigest
import javax.crypto.Cipher
import javax.crypto.spec.IvParameterSpec
import javax.crypto.spec.SecretKeySpec

// Bu dosya cloudstream_pydroid_tam.py tarafindan otomatik uretildi.
// Notlar: sayfalama dogrulanamadi
class Tavsiyefilmizle : MainAPI() {
    override var mainUrl = "https://tavsiyefilmizle.net"
    override var name = "Tavsiyefilmizle"
    override var lang = "tr"
    override val hasMainPage = true
    override val supportedTypes = setOf(TvType.Movie)

    private val ua =
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    private val baseHeaders = mapOf("User-Agent" to ua, "Accept" to "*/*")

    // ---------------------------------------------------------------- ANA SAYFA
    override val mainPage = mainPageOf(
        "$mainUrl/" to "Son Eklenenler",
        "$mainUrl/category/aksiyon-filmleri/" to "Aksiyon Filmleri",
        "$mainUrl/category/netflix-filmleri-izle/" to "Netflix Filmleri",
        "$mainUrl/category/hint-filmleri/" to "Hint Filmleri",
        "$mainUrl/category/yerli-filmler/" to "Yerli Filmler"
    )

    private fun pageUrl(base: String, page: Int): String =
        if (page <= 1) base else base.trimEnd('/') + "/page/$page/"

    override suspend fun getMainPage(page: Int, request: MainPageRequest): HomePageResponse {
        val doc = app.get(pageUrl(request.data, page), headers = baseHeaders).document
        val items = doc.select("div.movie-preview.existing_item.res_item").mapNotNull { it.toSearchResult() }.distinctBy { it.url }
        return newHomePageResponse(request.name, items, hasNext = items.isNotEmpty())
    }

    private fun Element.toSearchResult(): SearchResponse? {
        val a = selectFirst("a[href*=/filmler10/]") ?: return null
        val href = fixUrlNull(a.attr("href")) ?: return null
        val title = ((selectFirst("img")?.attr("alt")) ?: "").replace(Regex("""\s*(film(i)?\s+)?izle\s*$""", RegexOption.IGNORE_CASE), "").trim()
        if (title.isBlank()) return null
        val poster = fixUrlNull(selectFirst("img")?.attr("data-src"))
        return newMovieSearchResponse(title, href, TvType.Movie) { this.posterUrl = poster }
    }

    // ---------------------------------------------------------------- ARAMA
    override suspend fun search(query: String): List<SearchResponse> {
        val q = URLEncoder.encode(query, "UTF-8")
        val doc = app.get("$mainUrl/?s=$q", headers = baseHeaders).document
        return doc.select("div.movie-preview.existing_item.res_item").mapNotNull { it.toSearchResult() }.distinctBy { it.url }
    }

    // ---------------------------------------------------------------- DETAY
    override suspend fun load(url: String): LoadResponse? {
        val doc = app.get(url, headers = baseHeaders).document
        val title = (doc.selectFirst("h1")?.text() ?: doc.selectFirst("meta[property=og:title]")?.attr("content"))?.trim()
            ?.replace(Regex("""\s*(film(i)?\s+)?izle\s*(\|.*)?$""", RegexOption.IGNORE_CASE), "")?.trim()
            ?.takeIf { it.isNotBlank() } ?: return null
        val poster = fixUrlNull(doc.selectFirst("meta[property=og:image]")?.attr("content"))
        val plot = doc.selectFirst("meta[property=og:description]")?.attr("content")?.trim()
        val year = Regex("""\b(19|20)\d{2}\b""").find(title)?.value?.toIntOrNull()
        val tags = doc.select("div.Breadcrumb a[href*=/category/]").map { it.text().trim() }.filter { it.isNotBlank() }.distinct()
        val actors = emptyList<String>()
        val duration = Regex("""(\d{2,3})\s*(?:dk|dakika|min)\b""", RegexOption.IGNORE_CASE).find(doc.text())?.groupValues?.get(1)?.toIntOrNull()
        return newMovieLoadResponse(title, url, TvType.Movie, url) {
            this.posterUrl = poster
            this.plot = plot
            this.year = year
            this.tags = tags
            this.duration = duration
            addActors(actors)
        }
    }

    // ---------------------------------------------------------------- VIDEO
    override suspend fun loadLinks(
        data: String,
        isCasting: Boolean,
        subtitleCallback: (SubtitleFile) -> Unit,
        callback: (ExtractorLink) -> Unit
    ): Boolean {
        val page = app.get(data, headers = baseHeaders).document
        val embeds = page.select("iframe").mapNotNull { f ->
            listOf("data-litespeed-src", "data-src", "data-lazy-src", "src")
                .map { f.attr(it) }
                .firstOrNull { it.startsWith("http") || it.startsWith("//") }
        }.map { fixUrl(it) }.distinct()
        var found = false
        for (embed in embeds) {
            if (loadBePlayer(embed, data, subtitleCallback, callback)) found = true
            else if (loadExtractor(embed, data, subtitleCallback, callback)) found = true
        }
        return found
    }

    // iframe -> embed (Referer: film sayfasi) -> bePlayer(ARG1, JSON) -> AES coz -> video_location (master HLS)
    private suspend fun loadBePlayer(
        embed: String,
        referer: String,
        subtitleCallback: (SubtitleFile) -> Unit,
        callback: (ExtractorLink) -> Unit
    ): Boolean {
        val html = app.get(embed, referer = referer, headers = baseHeaders).text
        val m = Regex("""bePlayer\(\s*(['"])(.*?)\1\s*,\s*(['"])(\{.*?\})\3""", RegexOption.DOT_MATCHES_ALL)
            .find(html) ?: return false
        val arg1 = m.groupValues[2]
        val json = m.groupValues[4].replace("\\/", "/")
        val plain = decryptBePlayer(arg1, json) ?: return false
        val o = JSONObject(plain)
        val master = o.optString("video_location").takeIf { it.isNotBlank() } ?: return false
        val origin = "https://" + URI(embed).host

        o.optJSONArray("strSubtitles")?.let { arr ->
            for (i in 0 until arr.length()) {
                val s = arr.optJSONObject(i) ?: continue
                if (s.isNull("file")) continue
                val f = s.optString("file")
                if (f.isBlank()) continue
                val sub = if (f.startsWith("http")) f else origin + f
                subtitleCallback.invoke(newSubtitleFile(s.optString("label", "Türkçe"), sub))
            }
        }

        // Master istegi Referer(embed)+Origin ister, segmentler User-Agent ister. URL oturuma bagli: her oynatmada bastan coz.
        val streamHeaders = mapOf(
            "User-Agent" to ua,
            "Accept" to "*/*",
            "Referer" to embed,
            "Origin" to origin
        )
        callback.invoke(
            newExtractorLink(
                source = name,
                name = "$name HLS",
                url = master,
                type = ExtractorLinkType.M3U8
            ) {
                this.referer = embed
                this.quality = Qualities.Unknown.value
                this.headers = streamHeaders
            }
        )
        return true
    }

    private fun hexToBytes(s: String) = s.chunked(2).map { it.toInt(16).toByte() }.toByteArray()

    private fun evpKeyIv(pass: ByteArray, salt: ByteArray): Pair<ByteArray, ByteArray> {
        val md = MessageDigest.getInstance("MD5")
        var d = ByteArray(0)
        var prev = ByteArray(0)
        while (d.size < 48) {
            md.reset()
            prev = md.digest(prev + pass + salt)
            d += prev
        }
        return d.copyOfRange(0, 32) to d.copyOfRange(32, 48)
    }

    private fun decryptBePlayer(arg1: String, json: String): String? = try {
        val o = JSONObject(json)
        val passphrase = arg1
        val (key, iv) = evpKeyIv(passphrase.toByteArray(Charsets.UTF_8), hexToBytes(o.getString("s")))
        val cipher = Cipher.getInstance("AES/CBC/PKCS5Padding")
        cipher.init(Cipher.DECRYPT_MODE, SecretKeySpec(key, "AES"), IvParameterSpec(iv))
        String(cipher.doFinal(Base64.decode(o.getString("ct"), Base64.DEFAULT)), Charsets.UTF_8)
    } catch (e: Exception) {
        null
    }
}
