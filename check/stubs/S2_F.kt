package androidx.lifecycle
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.MainScope
open class ViewModel
val ViewModel.viewModelScope: CoroutineScope get() = MainScope()
