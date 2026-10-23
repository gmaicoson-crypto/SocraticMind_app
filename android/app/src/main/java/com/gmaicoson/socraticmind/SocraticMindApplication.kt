package com.gmaicoson.socraticmind

import android.app.Application
import com.gmaicoson.socraticmind.auth.AuthApi
import com.gmaicoson.socraticmind.auth.SessionStore
import com.gmaicoson.socraticmind.chat.ChatActionsApi
import com.gmaicoson.socraticmind.chat.ChatHistoryApi
import com.gmaicoson.socraticmind.chat.ChatTurnApi
import com.gmaicoson.socraticmind.chat.FileChatTurnJournal
import com.gmaicoson.socraticmind.network.ApiEndpoint
import com.gmaicoson.socraticmind.network.HttpTransport
import com.gmaicoson.socraticmind.storage.keystoreTokenVault

class SocraticMindApplication : Application() {
    val graph: Result<AppGraph> by lazy {
        runCatching {
            val endpoint =
                ApiEndpoint(
                    BuildConfig.API_BASE_URL,
                    if (BuildConfig.DEBUG) setOf("10.0.2.2", "127.0.0.1", "localhost") else emptySet(),
                )
            val transport = HttpTransport(endpoint)
            val api = AuthApi(transport)
            AppGraph(
                api,
                SessionStore(api, keystoreTokenVault(this, endpoint)),
                ChatHistoryApi(transport),
                ChatTurnApi(transport),
                FileChatTurnJournal(noBackupFilesDir, endpoint.credentialScope),
                ChatActionsApi(transport),
            )
        }
    }
}

class AppGraph(
    val auth: AuthApi,
    val session: SessionStore,
    val history: ChatHistoryApi,
    val turn: ChatTurnApi,
    val journal: FileChatTurnJournal,
    val actions: ChatActionsApi,
)
