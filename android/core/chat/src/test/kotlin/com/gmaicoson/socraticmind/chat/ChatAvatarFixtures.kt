package com.gmaicoson.socraticmind.chat

import kotlinx.serialization.json.Json
import java.nio.file.Files
import java.nio.file.Path

internal fun avatarFixture() =
    Json
        .parseToJsonElement(
            Files.readString(Path.of(System.getProperty("socratic.contracts")).resolve("chat-avatar.json")),
        ).historyObject()
