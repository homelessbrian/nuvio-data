package com.nuvio.tv.livetv.data
import com.nuvio.tv.livetv.model.EpgProgram
class EpgDatabase {
  var hits: List<Pair<String, EpgProgram>> = emptyList()
  var onAir: Map<String, List<EpgProgram>> = emptyMap()
  @Volatile var changes: Long = 1L
  fun findByWords(fromMs: Long, toMs: Long, minStopMs: Long, words: Collection<String>, inDescription: Boolean = true, limit: Int = 4_000): List<Pair<String, EpgProgram>> =
      hits.filter { (_, p) -> p.startMs >= fromMs && p.startMs < toMs && p.stopMs > minStopMs && words.any { w -> p.title.contains(w, true) || (inDescription && (p.description ?: "").contains(w, true)) } }
  fun scanListings(fromMs: Long, toMs: Long, minStopMs: Long, onRow: (ch: String, start: Long, stop: Long, title: String, descr: String?, cat: String?) -> Unit) {
      hits.forEach { (ch, p) -> if (p.startMs >= fromMs && p.startMs < toMs && p.stopMs > minStopMs) onRow(ch, p.startMs, p.stopMs, p.title, p.description, null) }
  }
  fun revision(): Long = changes
  class SportsRowsInfo(val stamp: String, val rev: Long, val fromMs: Long, val toMs: Long, val rows: Int)
  fun sportsRowsInfo(): SportsRowsInfo? = null
  fun sportsRowsWords(): Set<String> = emptySet()
  inner class SportsRowsWriter {
    var rows = 0
    fun add(ch: String, start: Long, stop: Long, title: String, descr: String?, cat: String?, nt: String, nd: String) { rows++ }
    fun finish(rev: Long, fromMs: Long, toMs: Long, words: Collection<String>): Boolean = false
    fun abort() {}
  }
  fun startSportsRows(): SportsRowsWriter = SportsRowsWriter()
  fun scanSportsRows(fromMs: Long, toMs: Long, minStopMs: Long, onRow: (ch: String, start: Long, stop: Long, title: String, descr: String?, cat: String?, nt: String, nd: String) -> Unit) {}
  fun range(fromMs: Long, toMs: Long, onlyChannel: String? = null, light: Boolean = false, channels: Collection<String>? = null): Map<String, List<EpgProgram>> =
      onAir.filterKeys { channels == null || it in channels }
}
