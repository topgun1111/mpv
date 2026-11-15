package kotlinx.serialization
@Target(AnnotationTarget.CLASS) annotation class Serializable
@RequiresOptIn annotation class ExperimentalSerializationApi
interface KSerializer<T>
inline fun <reified T> serializer(): KSerializer<T> = TODO()
