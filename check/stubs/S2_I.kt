package com.nuvio.tv.livetv.sports
object SportsLaunch { data class Catchup(val channelKey: String, val program: com.nuvio.tv.livetv.model.EpgProgram); fun catchup(c: Catchup) {} }
