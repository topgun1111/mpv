package kotlinx.coroutines
import kotlin.coroutines.*
typealias CancellationException = java.util.concurrent.CancellationException
interface Job : CoroutineContext.Element { val isActive: Boolean; fun cancel(cause: CancellationException? = null); companion object Key : CoroutineContext.Key<Job> }
fun Job(): Job = TODO()
fun SupervisorJob(parent: Job? = null): Job = TODO()
object NonCancellable : CoroutineContext by EmptyCoroutineContext
abstract class CoroutineDispatcher : CoroutineContext by EmptyCoroutineContext
object Dispatchers { val Default: CoroutineDispatcher = TODO(); val IO: CoroutineDispatcher = TODO(); val Main: CoroutineDispatcher = TODO() }
interface CoroutineScope { val coroutineContext: CoroutineContext }
fun CoroutineScope(c: CoroutineContext): CoroutineScope = TODO()
fun CoroutineScope.launch(context: CoroutineContext = EmptyCoroutineContext, block: suspend CoroutineScope.() -> Unit): Job = TODO()
suspend fun <T> withContext(context: CoroutineContext, block: suspend CoroutineScope.() -> T): T = TODO()
suspend fun delay(ms: Long) {}
suspend fun currentCoroutineContext(): CoroutineContext = TODO()
fun CoroutineScope.ensureActive() {}
fun Job.ensureActive() {}
fun CoroutineContext.ensureActive() {}
val CoroutineScope.isActive: Boolean get() = true
val CoroutineContext.isActive: Boolean get() = true
