package com.nuvio.tv.livetv.sports

import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.security.MessageDigest
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone

/*
 * Ready-made score files for the Nuvio + IPTV app, made from the shared ESPN cache (the espn folder)
 * with the app's own reader (SportsFeeds.parseScoreboard) and saved in the app's own short form
 * (SportsEventCodec). Each TV then only downloads a league that changed, already read, instead of
 * every league's raw ESPN answers.
 *
 * Writes (only when the content changed):
 *   espn/compact/day/<league>.json    yesterday, today, tomorrow (US Eastern days, like ESPN)
 *   espn/compact/week/<league>.json   the day after tomorrow to a week ahead
 *     {"v":1,"lg":"<league logo, if any>","g":[games]}
 *   espn/compact/index.json
 *     {"v":1,"at":<ms>,"day":[days],"week":[days],
 *      "leagues":{"<id>":{"d":"<day file hash>","ds":[<secs each day was fetched, 0 = missing>],
 *                         "w":"<week file hash>","ws":[...]}}}
 * The old files in the espn folder are left exactly as they are, for app versions that read those.
 *
 * Run: java ... CompactKt <espn folder>
 */

private const val DAY_MS = 86_400_000L
private const val DAYS_AHEAD = 7

fun main(args: Array<String>) {
    val dir = File(args.getOrElse(0) { "espn" })
    val out = File(dir, "compact")
    File(out, "day").mkdirs()
    File(out, "week").mkdirs()
    val now = System.currentTimeMillis()
    val fmt = SimpleDateFormat("yyyyMMdd", Locale.US).apply { timeZone = TimeZone.getTimeZone("America/New_York") }
    val dayDays = listOf(now - DAY_MS, now, now + DAY_MS).map { fmt.format(Date(it)) }
    val weekDays = (2..DAYS_AHEAD).map { fmt.format(Date(now + it * DAY_MS)) }

    val leagues = JSONObject()
    var written = 0
    var games = 0
    val files = dir.listFiles { f -> f.isFile && f.name.endsWith(".json") }.orEmpty().sortedBy { it.name }
    for (file in files) {
        val root = runCatching { JSONObject(file.readText()) }.getOrNull() ?: continue
        val id = root.optString("id").ifBlank { null } ?: continue
        val league = SportsCatalog.league(id)?.takeIf { it.espnPath != null } ?: continue
        val days = root.optJSONObject("days") ?: JSONObject()
        val safe = SportsFeeds.safeFileId(id)
        val entry = JSONObject()
        for ((window, wanted) in listOf("d" to dayDays, "w" to weekDays)) {
            val stamps = JSONArray()
            val raws = ArrayList<String>()
            for (d in wanted) {
                val o = days.optJSONObject(d)
                val raw = o?.optString("raw")?.ifBlank { null }
                if (o == null || raw == null) { stamps.put(0); continue }
                stamps.put(o.optLong("fetchedAt", 0L) / 1000)
                raws += raw
            }
            // Exactly what the app does with the same answers.
            val parsed = raws.flatMap { raw -> runCatching { SportsFeeds.parseScoreboard(league, raw) }.getOrDefault(emptyList()) }
                .distinctBy { it.id }
            games += parsed.size
            val logo = SportsFeeds.leagueLogos[league.id]
            val text = "{\"v\":1" + (logo?.let { ",\"lg\":" + JSONObject.quote(it) } ?: "") +
                ",\"g\":" + SportsEventCodec.encode(parsed) + "}\n"
            val target = File(out, (if (window == "d") "day/" else "week/") + "$safe.json")
            if (!target.exists() || target.readText() != text) { target.writeText(text); written++ }
            entry.put(window, hash(text)).put(window + "s", stamps)
        }
        leagues.put(id, entry)
    }
    val index = JSONObject().put("v", 1).put("at", now)
        .put("day", JSONArray(dayDays)).put("week", JSONArray(weekDays)).put("leagues", leagues)
    File(out, "index.json").writeText(index.toString() + "\n")
    println("Compact score files: ${leagues.length()} leagues, $games games, $written files changed")
}

private fun hash(text: String): String =
    MessageDigest.getInstance("SHA-256").digest(text.toByteArray()).joinToString("") { "%02x".format(it) }.take(16)
