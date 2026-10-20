package okhttp3
import java.util.concurrent.TimeUnit
class ResponseBody { fun string(): String = "" }
class Response : java.io.Closeable { val isSuccessful = true; val code = 200; val body: ResponseBody? = ResponseBody(); override fun close() {} }
class Call { fun execute(): Response = Response() }
class Request { class Builder { fun url(u: String) = this; fun header(a: String, b: String) = this; fun build() = Request() } }
class OkHttpClient {
  fun newCall(r: Request) = Call()
  class Builder {
    fun connectTimeout(a: Long, u: TimeUnit) = this
    fun readTimeout(a: Long, u: TimeUnit) = this
    fun callTimeout(a: Long, u: TimeUnit) = this
    fun followRedirects(b: Boolean) = this
    fun followSslRedirects(b: Boolean) = this
    fun retryOnConnectionFailure(b: Boolean) = this
    fun build() = OkHttpClient()
  }
}
