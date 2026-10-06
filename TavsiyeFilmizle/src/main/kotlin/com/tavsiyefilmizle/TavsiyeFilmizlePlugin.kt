package com.tavsiyefilmizle

import com.lagradost.cloudstream3.plugins.BasePlugin
import com.lagradost.cloudstream3.plugins.CloudstreamPlugin

@CloudstreamPlugin
class TavsiyeFilmizlePlugin : BasePlugin() {
    override fun load() {
        registerMainAPI(TavsiyeFilmizle())
    }
}
