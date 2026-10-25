package com.gmaicoson.socraticmind.network

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.toRequestBody

/** One bounded file plus small UTF-8 fields; take a snapshot before asynchronous transmission. */
class MultipartUpload(
    fields: Map<String, String>,
    fileField: String,
    filename: String,
    mimeType: String,
    bytes: ByteArray,
) {
    internal val body: RequestBody

    init {
        val values = fields.toMap()
        require(values.size <= 16 && values.keys.all { it.matches(Regex("[A-Za-z0-9_-]{1,64}")) })
        require(values.values.sumOf { it.toByteArray(Charsets.UTF_8).size } <= 16384)
        require(fileField.matches(Regex("[A-Za-z0-9_-]{1,64}")) && fileField !in values)
        require(filename.matches(Regex("[A-Za-z0-9_.-]{1,100}")))
        require(mimeType.matches(Regex("[a-z0-9.+_-]+/[a-z0-9.+_-]+")) && mimeType.length <= 100)
        require(bytes.size in 1..(5 * 1024 * 1024))
        body =
            MultipartBody
                .Builder()
                .setType(MultipartBody.FORM)
                .apply {
                    values.toSortedMap().forEach { (name, value) -> addFormDataPart(name, value) }
                    addFormDataPart(fileField, filename, bytes.copyOf().toRequestBody(mimeType.toMediaType()))
                }.build()
    }
}
