// Stand-ins for the app's build details (the check runs outside Android).
package android.os

object Build {
    const val MANUFACTURER = "GitHub"
    const val MODEL = "check"
    object VERSION { const val RELEASE = "-" }
}
