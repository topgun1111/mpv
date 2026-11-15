package kotlinx.serialization.json
import kotlinx.serialization.KSerializer
class JsonElement
object JsonNamingStrategy { val SnakeCase = Any() }
class JsonBuilder { var ignoreUnknownKeys = false; var explicitNulls = true; var encodeDefaults = false; var namingStrategy: Any? = null }
open class Json { 
  fun <T> encodeToString(s: KSerializer<T>, v: T): String = TODO()
  fun <T> decodeFromString(s: KSerializer<T>, t: String): T = TODO()
  inline fun <reified T> encodeToString(v: T): String = TODO()
  inline fun <reified T> decodeFromString(t: String): T = TODO()
  companion object Default : Json() }
fun Json(from: Json = Json.Default, b: JsonBuilder.() -> Unit): Json = Json.Default
