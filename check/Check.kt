package com.nuvio.tv.livetv.sports

import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone

/*
 * ESPN check for the Nuvio + IPTV Sports page. Runs the app's own Sports code (from the
 * Nuvio_Testing repo) against ESPN's live feeds for every league, and writes a report:
 * what each league's feed gives (games, scores, winners, colours, logos, TV networks, race
 * results, scoring plays, team schedules) and anything that looks wrong.
 *
 * Nothing here is sent anywhere: it only reads ESPN's public feeds.
 */

private const val ESPN = "https://site.api.espn.com/apis/site/v2/sports/"
private const val DAY = 86_400_000L

/** Why the last request failed (status and the start of ESPN's answer), for the report. */
private var lastError = ""

private fun fetch(url: String): String? = runCatching {
    val c = URL(url).openConnection() as HttpURLConnection
    c.connectTimeout = 15_000
    c.readTimeout = 30_000
    c.setRequestProperty("User-Agent", "Mozilla/5.0 (nuvio-data ESPN check)")
    c.setRequestProperty("Accept", "application/json")
    val code = c.responseCode
    if (code != 200) {
        lastError = "HTTP $code: " + (runCatching { c.errorStream?.bufferedReader()?.readText() }.getOrNull() ?: "").take(160).replace("\n", " ")
        null
    } else c.inputStream.bufferedReader().readText()
}.onFailure { lastError = it.javaClass.simpleName + ": " + it.message }.getOrNull().also { Thread.sleep(250) }

/** Asking for several days at once: which forms of the request ESPN takes (the app asks for ranges). */
private fun rangeProbe(md: StringBuilder, now: Long) {
    md.appendLine("### Asking for several days at once")
    md.appendLine()
    md.appendLine("| League | Request | Answer |")
    md.appendLine("|---|---|---|")
    for (id in listOf("football/nfl", "soccer/eng.1", "hockey/nhl")) {
        val l = SportsCatalog.league(id) ?: continue
        val base = "$ESPN${l.espnPath}/scoreboard"
        val tries = listOf(
            "7 days, limit" to "$base?dates=${day(now)}-${day(now + 7 * DAY)}&limit=1000",
            "7 days" to "$base?dates=${day(now)}-${day(now + 7 * DAY)}",
            "2 days" to "$base?dates=${day(now)}-${day(now + DAY)}",
            "1 day, limit" to "$base?dates=${day(now)}&limit=1000",
            "month" to "$base?dates=${day(now).take(6)}",
            "week param" to "$base?week=8&seasontype=2"
        )
        for ((label, url) in tries) {
            val raw = fetch(url)
            val n = raw?.let { runCatching { JSONObject(it).optJSONArray("events")?.length() ?: 0 }.getOrDefault(-1) }
            md.appendLine("| ${l.name} | $label | " + (if (raw != null) "OK, $n events" else lastError.replace("|", "/")) + " |")
        }
    }
    md.appendLine()
}

private val dayFmt = SimpleDateFormat("yyyyMMdd", Locale.US).apply { timeZone = TimeZone.getTimeZone("America/New_York") }
private fun day(ms: Long) = dayFmt.format(Date(ms))

private fun pct(n: Int, of: Int) = if (of == 0) "–" else "${n * 100 / of}%"

private class Row(val league: League, val cells: List<String>, val problems: List<String>)

fun main(args: Array<String>) {
    val out = File(args.getOrElse(0) { "espn-report.md" })
    val now = System.currentTimeMillis()
    val teamRows = ArrayList<Row>()
    val eventRows = ArrayList<Row>()
    val leagues = SportsCatalog.leagues.filter { it.espnPath != null }
    println("Checking ${leagues.size} leagues…")

    for (l in leagues) {
        val problems = ArrayList<String>()
        // The same requests the app makes: last week, and today to a week ahead (one request
        // each); a feed that won't take a range of days: yesterday, today and tomorrow.
        var raws = listOfNotNull(
            fetch("$ESPN${l.espnPath}/scoreboard?dates=${day(now - 7 * DAY)}-${day(now - DAY)}&limit=1000${l.espnQuery}"),
            fetch("$ESPN${l.espnPath}/scoreboard?dates=${day(now)}-${day(now + 7 * DAY)}&limit=1000${l.espnQuery}")
        )
        if (raws.isEmpty()) {
            problems += "won't take a range of days (the app asks a day at a time; $lastError)"
            raws = listOf(-1, 0, 1).mapNotNull { d -> fetch("$ESPN${l.espnPath}/scoreboard?dates=${day(now + d * DAY)}&limit=1000${l.espnQuery}") }
        }
        if (raws.isEmpty()) {
            raws = listOfNotNull(fetch("$ESPN${l.espnPath}/scoreboard?limit=1000${l.espnQuery}"))
            if (raws.isNotEmpty()) problems += "only the feed's own default days work"
        }
        if (raws.isEmpty()) {
            problems += "the feed didn't answer at all"
            (if (l.kind == LeagueKind.TEAMS) teamRows else eventRows) += Row(l, listOf("–"), problems)
            continue
        }
        val events = raws.flatMap { raw ->
            runCatching { SportsFeeds.parseScoreboard(l, raw) }.getOrElse { e -> problems += "couldn't read the feed: ${e.message}"; emptyList() }
        }.distinctBy { it.id }
        val logo = SportsFeeds.leagueLogos[l.id] != null
        val post = events.filter { it.state == GameState.POST }
        val live = events.filter { it.state == GameState.LIVE }
        val pre = events.filter { it.state == GameState.PRE }
        val off = events.filter { it.state == GameState.OFF }
        if (events.isEmpty()) problems += "no games in the last week or the next (off season?)"

        if (l.kind == LeagueKind.TEAMS) {
            val two = events.count { it.sides.size == 2 }
            if (events.isNotEmpty() && two < events.size) problems += "${events.size - two} games without two teams"
            val scored = post.count { it.hasScore }
            if (post.isNotEmpty() && scored < post.size) problems += "${post.size - scored} finished games without a score"
            val winners = post.count { ev -> ev.sides.any { it.winner } }
            val ties = post.count { ev -> ev.hasScore && ev.sides.map { it.score }.distinct().size == 1 }
            if (post.isNotEmpty() && winners + ties < post.size) problems += "${post.size - winners - ties} finished games with no winner marked"
            val sides = events.flatMap { it.sides }
            val colours = sides.count { it.team.color != null || it.team.altColor != null }
            val logos = sides.count { it.team.logo != null }
            if (sides.isNotEmpty() && colours * 10 < sides.size * 9) problems += "team colours missing on ${pct(sides.size - colours, sides.size)} of teams"
            if (sides.isNotEmpty() && logos * 10 < sides.size * 9) problems += "team logos missing on ${pct(sides.size - logos, sides.size)} of teams"
            val tv = (pre + live).count { it.broadcasts.isNotEmpty() }
            val liveStatus = live.count { it.status != null }

            // Scoring plays (Latest Scoring) for a finished game.
            var plays = "–"
            post.firstOrNull { it.espnId != null }?.let { g ->
                val raw = fetch("$ESPN${l.espnPath}/summary?event=${g.espnId}")
                plays = if (raw == null) "no answer" else {
                    val n = runCatching { SportsFeeds.parseSummary(JSONObject(raw)).size }.getOrDefault(-1)
                    if (n == 0 && g.hasScore && g.sides.any { (it.score?.toDoubleOrNull() ?: 0.0) > 0 }) problems += "no scoring plays read for a game that had scoring (${g.title})"
                    if (n < 0) "unreadable" else "$n"
                }
            }

            // A team's season (My Sports rows): the first team in the league.
            var season = "–"
            val teamsRaw = fetch("$ESPN${l.espnPath}/teams?limit=1000")
            val team = teamsRaw?.let { runCatching { SportsFeeds.parseTeams(l, it) }.getOrNull() }?.firstOrNull()
            if (teamsRaw == null || team == null) problems += "couldn't get the league's teams (Follow Teams & Leagues)"
            else {
                val sch = listOfNotNull(
                    fetch("$ESPN${l.espnPath}/teams/${team.id}/schedule"),
                    if (l.espnPath!!.startsWith("soccer/")) fetch("$ESPN${l.espnPath}/teams/${team.id}/schedule?fixture=true") else null
                ).flatMap { runCatching { SportsFeeds.parseSchedule(l, it) }.getOrDefault(emptyList()) }.distinctBy { it.espnId ?: it.id }
                val ahead = sch.count { it.startMs > now }
                season = "${team.name}: ${sch.size} (${ahead} ahead)"
                if (sch.isEmpty()) problems += "${team.name}'s schedule came back empty"
                val others = sch.map { it.leagueId }.distinct().filter { it != l.id }
                if (others.isNotEmpty()) season += " · also " + others.joinToString { SportsCatalog.league(it)?.short ?: it }
            }

            teamRows += Row(l, listOf(
                "${post.size} / ${live.size} / ${pre.size}" + if (off.isNotEmpty()) " / ${off.size} off" else "",
                "${pct(scored, post.size)} · ${pct(winners + ties, post.size)}",
                if (live.isEmpty()) "–" else pct(liveStatus, live.size),
                "${pct(colours, sides.size)} · ${pct(logos, sides.size)}",
                pct(tv, pre.size + live.size),
                plays,
                season,
                if (logo) "yes" else "no"
            ), problems)
        } else {
            val done = post + live
            val withResults = done.count { it.standings.isNotEmpty() }
            if (done.isNotEmpty() && withResults == 0) problems += "no results / running order read for finished or live events"
            val multi = events.count { !it.hasTime }
            val stillOn = events.count { !it.hasTime && it.state == GameState.LIVE }
            val example = (live + post).firstOrNull { it.standings.isNotEmpty() }?.let { ev ->
                ev.title.take(28) + ": " + ev.standings.take(3).joinToString(", ") { s -> (if (s.pos.isNotBlank()) s.pos + " " else "") + s.name + (s.detail?.let { d -> " $d" } ?: "") }
            } ?: "–"
            eventRows += Row(l, listOf(
                "${post.size} / ${live.size} / ${pre.size}",
                if (done.isEmpty()) "–" else pct(withResults, done.size),
                "$multi multi-day ($stillOn still on)",
                pct((pre + live).count { it.broadcasts.isNotEmpty() }, pre.size + live.size),
                example.replace("|", "/"),
                if (logo) "yes" else "no"
            ), problems)
        }
        println("  ${l.name}: ${events.size} events" + if (problems.isEmpty()) "" else " (${problems.size} to check)")
    }

    val md = StringBuilder()
    md.appendLine("## ESPN check")
    md.appendLine()
    md.appendLine("The app's own Sports code, run against ESPN's feeds for every league: the last week and the week ahead.")
    md.appendLine()
    rangeProbe(md, now)
    md.appendLine("### Leagues with teams")
    md.appendLine()
    md.appendLine("| League | Finished / live / coming | Finished: score · winner | Live: clock | Teams: colours · logos | TV listed | Scoring plays (a finished game) | A team's season | League logo |")
    md.appendLine("|---|---|---|---|---|---|---|---|---|")
    teamRows.forEach { r -> md.appendLine("| ${r.league.name} | " + r.cells.joinToString(" | ").padEnd(0) + if (r.cells.size == 1) " | | | | | | | |" else " |") }
    md.appendLine()
    md.appendLine("### Events (races, fights, golf, tennis)")
    md.appendLine()
    md.appendLine("| League | Finished / live / coming | Results read | Multi-day | TV listed | Example | League logo |")
    md.appendLine("|---|---|---|---|---|---|---|")
    eventRows.forEach { r -> md.appendLine("| ${r.league.name} | " + r.cells.joinToString(" | ") + if (r.cells.size == 1) " | | | | | |" else " |") }
    md.appendLine()
    val all = teamRows + eventRows
    val flagged = all.filter { it.problems.isNotEmpty() }
    md.appendLine("### To look at (${flagged.size} of ${all.size} leagues)")
    md.appendLine()
    if (flagged.isEmpty()) md.appendLine("Nothing: every league's feed read as expected.")
    flagged.forEach { r -> md.appendLine("- **${r.league.name}**: " + r.problems.joinToString("; ")) }
    out.writeText(md.toString())
    println("Report written to ${out.path}")
}
