package com.nuvio.tv.livetv.player
import com.nuvio.tv.livetv.model.LiveChannel
import kotlinx.coroutines.flow.*
data class LivePlaybackState(val channelKey: String? = null)
class LiveTvPlaybackController { val state: StateFlow<LivePlaybackState> = MutableStateFlow(LivePlaybackState()); fun play(channel: LiveChannel) {} }
