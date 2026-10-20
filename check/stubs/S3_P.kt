package com.nuvio.tv.livetv.data
import com.nuvio.tv.livetv.model.LiveChannel
class LiveTvPosterResolver { companion object { fun is247(c: LiveChannel): Boolean = Regex("""(?i)\b24\s*[/\\|\-x]?\s*7\b""").containsMatchIn(c.name) } }
