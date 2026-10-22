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
        // ESPN doesn't take a range of days (the app asks a day at a time) but does take a month:
        // the months the last week and the next five weeks touch, kept to that window.
        val months = SimpleDateFormat("yyyyMM", Locale.US).apply { timeZone = TimeZone.getTimeZone("America/New_York") }
        val wanted = listOf(now - 7 * DAY, now, now + 7 * DAY, now + 35 * DAY).map { months.format(Date(it)) }.distinct()
        var raws = wanted.mapNotNull { m -> fetch("$ESPN${l.espnPath}/scoreboard?dates=$m&limit=1000${l.espnQuery}") }
        if (raws.isEmpty()) {
            problems += "won't take a month either ($lastError): the week ahead still works, a day at a time"
            raws = listOf(-1, 0, 1).mapNotNull { d -> fetch("$ESPN${l.espnPath}/scoreboard?dates=${day(now + d * DAY)}&limit=1000${l.espnQuery}") }
        }
        if (raws.isEmpty()) {
            raws = listOfNotNull(fetch("$ESPN${l.espnPath}/scoreboard?limit=1000${l.espnQuery}"))
            if (raws.isNotEmpty()) problems += "only the feed's own default days work"
        }
        if (raws.isEmpty()) {
            problems += "the feed didn't answer at all ($lastError)"
            (if (l.kind == LeagueKind.TEAMS) teamRows else eventRows) += Row(l, listOf("–"), problems)
            continue
        }
        val events = raws.flatMap { raw ->
            runCatching { SportsFeeds.parseScoreboard(l, raw) }.getOrElse { e -> problems += "couldn't read the feed: ${e.message}"; emptyList() }
        }.distinctBy { it.id }.filter { it.startMs in (now - 7 * DAY)..(now + 7 * DAY) || it.state == GameState.LIVE }
        val aheadCount = raws.flatMap { raw -> runCatching { SportsFeeds.parseScoreboard(l, raw) }.getOrDefault(emptyList()) }
            .distinctBy { it.id }.count { it.startMs in (now + 7 * DAY)..(now + 35 * DAY) }
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

            // Scoring plays (Latest Scoring) for a finished game, and what the game page's panels get.
            var plays = "–"
            var after = "–"
            post.firstOrNull { it.espnId != null }?.let { g ->
                val raw = fetch("$ESPN${l.espnPath}/summary?event=${g.espnId}")
                plays = if (raw == null) "no answer" else {
                    val n = runCatching { SportsFeeds.parseSummary(JSONObject(raw)).size }.getOrDefault(-1)
                    if (n == 0 && g.hasScore && g.sides.any { (it.score?.toDoubleOrNull() ?: 0.0) > 0 }) problems += "no scoring plays read for a game that had scoring (${g.title})"
                    if (n < 0) "unreadable" else "$n"
                }
                if (raw != null) after = extrasNote(raw, g, l, problems)
            }
            var before = "–"
            pre.firstOrNull { it.espnId != null }?.let { g ->
                fetch("$ESPN${l.espnPath}/summary?event=${g.espnId}")?.let { before = extrasNote(it, g, l, problems) }
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

            val tableNote = tableNote(l, problems)
            teamRows += Row(l, listOf(
                "${post.size} / ${live.size} / ${pre.size}" + (if (off.isNotEmpty()) " / ${off.size} off" else "") + " · $aheadCount later",
                "${pct(scored, post.size)} · ${pct(winners + ties, post.size)}",
                if (live.isEmpty()) "–" else pct(liveStatus, live.size),
                "${pct(colours, sides.size)} · ${pct(logos, sides.size)}",
                pct(tv, pre.size + live.size),
                plays,
                "before: $before<br>after: $after",
                season,
                tableNote,
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
                if (l.sport == Sport.RACING) tableNote(l, problems) else "–",
                if (logo) "yes" else "no"
            ), problems)
        }
        println("  ${l.name}: ${events.size} events" + if (problems.isEmpty()) "" else " (${problems.size} to check)")
    }

    val md = StringBuilder()
    md.appendLine("## ESPN check")
    md.appendLine()
    md.appendLine("The app's own Sports code, run against ESPN's feeds for every league: the last week, the week ahead, and up to five weeks ahead (asked by month, as the app now does).")
    md.appendLine()
    md.appendLine("### Leagues with teams")
    md.appendLine()
    md.appendLine("| League | Finished / live / coming (2 weeks) · later (5 weeks) | Finished: score · winner | Live: clock | Teams: colours · logos | TV listed | Scoring plays (a finished game) | Game page panels | A team's season | Table | League logo |")
    md.appendLine("|---|---|---|---|---|---|---|---|---|---|---|")
    teamRows.forEach { r -> md.appendLine("| ${r.league.name} | " + r.cells.joinToString(" | ").padEnd(0) + if (r.cells.size == 1) " | | | | | | | | | |" else " |") }
    md.appendLine()
    md.appendLine("### Events (races, fights, golf, tennis)")
    md.appendLine()
    md.appendLine("| League | Finished / live / coming | Results read | Multi-day | TV listed | Example | Table | League logo |")
    md.appendLine("|---|---|---|---|---|---|---|---|")
    eventRows.forEach { r -> md.appendLine("| ${r.league.name} | " + r.cells.joinToString(" | ") + if (r.cells.size == 1) " | | | | | | |" else " |") }
    md.appendLine()
    val all = teamRows + eventRows
    val flagged = all.filter { it.problems.isNotEmpty() }
    md.appendLine("### To look at (${flagged.size} of ${all.size} leagues)")
    md.appendLine()
    if (flagged.isEmpty()) md.appendLine("Nothing: every league's feed read as expected.")
    flagged.forEach { r -> md.appendLine("- **${r.league.name}**: " + r.problems.joinToString("; ")) }
    md.appendLine()
    // Done last, so a slow listing never gets in the way of the checks above.
    runCatching { coverage(md, now) }.onFailure { md.appendLine("Coverage: couldn't finish (${it.message}).") }
    out.writeText(md.toString())
    println("Report written to ${out.path}")
}


// ------------------------------------------------------------------ coverage

/** ESPN's sports, as its own listing names them (site paths start with the same word). */
private val COVER_SPORTS = listOf(
    "football", "basketball", "baseball", "hockey", "soccer", "rugby", "rugby-league",
    "australian-football", "cricket", "lacrosse", "volleyball", "field-hockey", "mma", "golf", "tennis", "racing"
)

private const val CORE = "http://sports.core.api.espn.com/v2/sports/"

/** Like [fetch], but follows ESPN's https-to-http redirects (Java won't on its own). */
private fun fetchFollow(start: String): String? {
    var url = start
    repeat(4) {
        val r = runCatching {
            val c = URL(url).openConnection() as HttpURLConnection
            c.instanceFollowRedirects = false
            c.connectTimeout = 15_000
            c.readTimeout = 30_000
            c.setRequestProperty("User-Agent", "Mozilla/5.0 (nuvio-data ESPN check)")
            c.setRequestProperty("Accept", "application/json")
            val code = c.responseCode
            when {
                code in 300..399 -> { url = c.getHeaderField("Location") ?: return null; null }
                code != 200 -> { lastError = "HTTP $code"; return null }
                else -> c.inputStream.bufferedReader().readText()
            }
        }.onFailure { lastError = it.javaClass.simpleName + ": " + it.message }.also { Thread.sleep(150) }
        if (r.isFailure) return null
        r.getOrNull()?.let { return it }
    }
    return null
}

private class Found(val sport: String, val path: String, val name: String, val games: Int, val withTeams: Int)

/**
 * Every league ESPN lists, against the app's own list: the ones the app doesn't have, busiest
 * first (games this month and next), so a missing league (or a missing sport) shows up here
 * before someone goes looking for their team and can't find it.
 */
private fun coverage(md: StringBuilder, now: Long) {
    println("Coverage: listing ESPN's leagues…")
    val have = SportsCatalog.leagues.mapNotNull { it.espnPath }.toSet()
    val months = SimpleDateFormat("yyyyMM", Locale.US).apply { timeZone = TimeZone.getTimeZone("America/New_York") }
    val thisMonth = months.format(Date(now))
    val nextMonth = months.format(Date(now + 31 * DAY))
    val missing = ArrayList<Found>()
    val listed = HashSet<String>()
    val couldnt = ArrayList<String>()
    for (sport in COVER_SPORTS) {
        val keys = ArrayList<String>()
        var page = 1
        while (page <= 10) {
            val raw = fetchFollow("${CORE}$sport/leagues?limit=500&page=$page") ?: break
            val o = runCatching { JSONObject(raw) }.getOrNull() ?: break
            val items = o.optJSONArray("items") ?: break
            for (i in 0 until items.length()) {
                val ref = items.optJSONObject(i)?.optString("\$ref").orEmpty()
                ref.substringBefore("?").substringAfter("/leagues/", "").takeIf { it.isNotBlank() }?.let { keys += it }
            }
            if (page >= o.optInt("pageCount", 1)) break
            page++
        }
        if (keys.isEmpty()) { couldnt += "$sport ($lastError)"; continue }
        println("  $sport: ${keys.size} leagues")
        for (key in keys) {
            // The league's own record: its name, and the slug the scoreboard takes (eng.1, nfl…).
            val info = fetchFollow("${CORE}$sport/leagues/$key")?.let { runCatching { JSONObject(it) }.getOrNull() }
            val slug = info?.optString("slug").orEmpty().ifBlank { key }
            val paths = listOf("$sport/$slug", "$sport/$key").distinct()
            paths.forEach { listed += it }
            if (paths.any { it in have }) continue
            val name = info?.optString("name").orEmpty().ifBlank { info?.optString("abbreviation").orEmpty() }.ifBlank { slug }
            var games = 0
            var withTeams = 0
            for (m in listOf(thisMonth, nextMonth)) {
                val sb = fetch("$ESPN${paths.first()}/scoreboard?dates=$m&limit=1000")?.let { runCatching { JSONObject(it) }.getOrNull() } ?: continue
                val evs = sb.optJSONArray("events") ?: continue
                for (i in 0 until evs.length()) {
                    games++
                    val comp = evs.optJSONObject(i)?.optJSONArray("competitions")?.optJSONObject(0)
                    if ((comp?.optJSONArray("competitors")?.length() ?: 0) == 2) withTeams++
                }
            }
            missing += Found(sport, paths.first(), name, games, withTeams)
        }
    }

    md.appendLine("### Coverage: leagues ESPN has that the app doesn't")
    md.appendLine()
    md.appendLine("Every league in ESPN's own listing, against the app's list. Busiest first (games this month and next). A league here can't be followed, and its teams can't be found in search.")
    md.appendLine()
    if (couldnt.isNotEmpty()) { md.appendLine("Couldn't list: " + couldnt.joinToString(", ")); md.appendLine() }
    val sportsInApp = have.map { it.substringBefore("/") }.toSet()
    val newSports = missing.map { it.sport }.distinct().filter { it !in sportsInApp }
    if (newSports.isNotEmpty()) { md.appendLine("**Sports the app has nothing from ESPN for:** " + newSports.joinToString(", ")); md.appendLine() }
    val busy = missing.filter { it.games > 0 }.sortedByDescending { it.games }
    md.appendLine("| Sport | League | ESPN path | Games (this month + next) | With two teams |")
    md.appendLine("|---|---|---|---|---|")
    busy.forEach { f -> md.appendLine("| ${f.sport} | ${f.name.replace("|", "/")} | `${f.path}` | ${f.games} | ${f.withTeams} |") }
    if (busy.isEmpty()) md.appendLine("| – | nothing with games coming up | | | |")
    md.appendLine()
    val quiet = missing.filter { it.games == 0 }
    if (quiet.isNotEmpty()) {
        md.appendLine("<details><summary>${quiet.size} more with no games this month or next (off season, or finished)</summary>")
        md.appendLine()
        quiet.groupBy { it.sport }.forEach { (sp, l) -> md.appendLine("- **$sp**: " + l.joinToString(", ") { "${it.name} (`${it.path}`)" }) }
        md.appendLine()
        md.appendLine("</details>")
        md.appendLine()
    }
    // And the other way round: a league in the app that ESPN no longer lists.
    val gone = SportsCatalog.leagues.filter { l -> l.espnPath != null && l.espnPath!!.substringBefore("/") in COVER_SPORTS && l.espnPath!!.substringBefore("/") !in couldnt.map { it.substringBefore(" ") } && l.espnPath !in listed }
    if (gone.isNotEmpty()) {
        md.appendLine("**In the app but not in ESPN's listing** (may have moved): " + gone.joinToString(", ") { "${it.name} (`${it.espnPath}`)" })
        md.appendLine()
    }
    println("Coverage: ${missing.size} leagues the app doesn't have (${busy.size} with games coming up)")
}


/** What a game's summary gives the panels under the game page: "stats 6 · leaders 4 · table 8 · venue · chances". */
/**
 * The league's table as the Tables page reads it: how many teams (or drivers), in how many groups,
 * the columns, and the leader. "none" for a league without one (a cup: left off the Tables page).
 */
private fun tableNote(l: League, problems: MutableList<String>): String {
    val url = Standings.espnUrl(l) ?: return "–"
    val raw = fetch(url) ?: return "no answer ($lastError)"
    val t = runCatching { Standings.parseEspn(l, raw) }.getOrElse { e ->
        problems += "couldn't read the table: ${e.message}"
        return "unreadable"
    } ?: return "none"
    val rows = t.groups.sumOf { it.rows.size }
    if (rows == 0) return "none"
    val lead = t.groups.first().rows.firstOrNull()
    val zones = t.groups.flatMap { g -> g.rows.mapNotNull { it.zone?.label } }.distinct()
    val noValues = t.groups.flatMap { it.rows }.count { r -> t.columns.any { c -> c.key != "behind" && r.values[c.key].isNullOrBlank() } }
    if (noValues > 0) problems += "$noValues table rows with empty columns"
    return "$rows in ${t.groups.size} group(s) · ${t.columns.joinToString(" ") { it.label }}" +
        (lead?.let { "<br>1st: ${it.name.replace("|", "/")}" } ?: "") +
        (if (t.hasDivisions) "<br>conferences: ${t.conferences.size}" else "") +
        (if (zones.isNotEmpty()) "<br>zones: ${zones.joinToString(", ")}" else "") +
        (t.season?.let { "<br>season $it" } ?: "")
}

private fun extrasNote(raw: String, g: SportsEvent, l: League, problems: MutableList<String>): String {
    val x = runCatching { SportsExtras.parse(JSONObject(raw), g, l.sport) }.getOrElse { e ->
        problems += "game page panels: couldn't read the summary (${e.message})"; return "unreadable"
    }
    val parts = listOfNotNull(
        x.stats.size.takeIf { it > 0 }?.let { "stats $it" },
        x.performers.size.takeIf { it > 0 }?.let { "leaders $it" },
        x.lineups.size.takeIf { it > 0 }?.let { "line-ups" },
        x.form.size.takeIf { it > 0 }?.let { "form $it" },
        x.meetings.size.takeIf { it > 0 }?.let { "meetings $it" },
        x.table.size.takeIf { it > 0 }?.let { "table ${it}" },
        if (x.hasMatchInfo) "venue" else null,
        if (x.hasOdds) "chances" else null,
        x.winHistory.size.takeIf { it > 1 }?.let { "chance line" }
    )
    return parts.joinToString(" · ").ifBlank { "nothing" }
}
