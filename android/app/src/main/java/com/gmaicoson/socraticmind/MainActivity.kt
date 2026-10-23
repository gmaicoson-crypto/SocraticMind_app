package com.gmaicoson.socraticmind

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.lifecycle.ViewModelProvider
import com.gmaicoson.socraticmind.account.AppRoot
import com.gmaicoson.socraticmind.account.AppViewModel

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val graph = (application as SocraticMindApplication).graph
        val model = ViewModelProvider(this, AppViewModel.Factory(graph))[AppViewModel::class.java]
        setContent { AppRoot(model) }
    }
}
