package com.nuvio.tv.livetv.data

import okhttp3.OkHttpClient

/** The app's shared web client (ForkHttp.kt in the app); here just a plain client, like the other stand-ins. */
internal object ForkHttp {
    val base: OkHttpClient by lazy { OkHttpClient() }

    fun builder(): OkHttpClient.Builder = OkHttpClient.Builder()
}
