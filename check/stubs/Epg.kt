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
  fun range(fromMs: Long, toMs: Long, onlyChannel: String? = null, light: Boolean = false, channels: Collection<String>? = null): Map<String, List<EpgProgram>> =
      onAir.filterKeys { channels == null || it in channels }
}
