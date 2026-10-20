package com.nuvio.tv.livetv.data
import com.nuvio.tv.livetv.model.*
import kotlinx.coroutines.flow.*
class LiveTvPreferences {
    val sportsSettingsJson: Flow<String?> = MutableStateFlow(null)
    val sportsMineJson: Flow<String?> = MutableStateFlow(null)
    suspend fun editSportsSettings(transform: (String?) -> String) {}
    suspend fun editSportsMine(transform: (String?) -> String) {}
    val settings: Flow<LiveTvSettings> = MutableStateFlow(LiveTvSettings())
    val userState: Flow<LiveUserState> = MutableStateFlow(LiveUserState())
}
data class LiveTvStatus(val loading: Boolean = false, val message: String? = null, val error: String? = null, val loadedOnce: Boolean = false, val quiet: Boolean = false)
class LiveTvRepository {
    val channels: StateFlow<List<LiveChannel>> = MutableStateFlow(emptyList())
    val status: StateFlow<LiveTvStatus> = MutableStateFlow(LiveTvStatus())
    fun ensureLoaded(updateCheckDelayMs: Long = 0L) {}
}
class LiveTvChannelStore { val displayChannels: StateFlow<List<LiveChannel>> = MutableStateFlow(emptyList()) }
