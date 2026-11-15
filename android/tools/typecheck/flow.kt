package kotlinx.coroutines.flow
interface StateFlow<T> { val value: T }
interface MutableStateFlow<T> : StateFlow<T> { override var value: T }
fun <T> MutableStateFlow(v: T): MutableStateFlow<T> = TODO()
fun <T> MutableStateFlow<T>.asStateFlow(): StateFlow<T> = this
inline fun <T> MutableStateFlow<T>.update(f: (T) -> T) { value = f(value) }
