package com.darkneslord.tavsiyefilmtest

import android.content.Context
import com.lagradost.cloudstream3.plugins.CloudstreamPlugin
import com.lagradost.cloudstream3.plugins.Plugin

@CloudstreamPlugin
class TavsiyeFilmTestPlugin : Plugin() {
    override fun load(context: Context) {
        registerMainAPI(TavsiyeFilmTest())
    }
}
