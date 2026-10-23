package com.gmaicoson.socraticmind.chat.markdown

import okhttp3.HttpUrl.Companion.toHttpUrlOrNull

object MarkdownLink {
    private val encodedControl = Regex("%(?:0[0-9a-f]|1[0-9a-f]|7f)", RegexOption.IGNORE_CASE)
    private val invalidEscape = Regex("%(?![0-9a-fA-F]{2})")

    /** Browser navigation only: no relative URLs, credentials, hidden controls or alternate schemes. */
    fun safe(value: String): String? {
        if (value.any {
                it.isWhitespace() || it.isISOControl() || Character.getType(it) == Character.FORMAT.toInt() ||
                    it == '\\'
            } || encodedControl.containsMatchIn(value) || invalidEscape.containsMatchIn(value)
        ) {
            return null
        }
        if (!value.startsWith("https://", ignoreCase = true) &&
            !value.startsWith("http://", ignoreCase = true)
        ) {
            return null
        }
        val url = value.toHttpUrlOrNull() ?: return null
        if (url.username.isNotEmpty() || url.password.isNotEmpty()) return null
        return url.toString()
    }
}
