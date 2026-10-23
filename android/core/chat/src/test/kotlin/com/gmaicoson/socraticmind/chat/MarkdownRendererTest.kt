package com.gmaicoson.socraticmind.chat

import com.gmaicoson.socraticmind.chat.markdown.MarkdownParser
import com.gmaicoson.socraticmind.chat.markdown.MarkdownRenderer
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.async
import kotlinx.coroutines.runBlocking
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertThrows
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger

class MarkdownRendererTest {
    @Test
    fun reusesRecentEntriesAndEvictsLeastRecentlyUsed() =
        runBlocking {
            val calls = Calls()
            val renderer = MarkdownRenderer(2, 1024, calls::parse)
            assertEquals(MarkdownParser.parse("a"), renderer.render("a"))
            renderer.render("b")
            renderer.render("a")
            renderer.render("c")
            renderer.render("b")
            assertEquals(1, calls.count("a"))
            assertEquals(2, calls.count("b"))
            assertEquals(1, calls.count("c"))
        }

    @Test
    fun appliesUtf8BudgetAndDoesNotCacheOversizedMessages() =
        runBlocking {
            val calls = Calls()
            val renderer = MarkdownRenderer(8, 6, calls::parse)
            renderer.render("甲")
            renderer.render("乙")
            renderer.render("甲")
            renderer.render("丙")
            renderer.render("超出预算")
            renderer.render("超出预算")
            renderer.render("甲")
            renderer.render("乙")
            assertEquals(1, calls.count("甲"))
            assertEquals(2, calls.count("乙"))
            assertEquals(2, calls.count("超出预算"))
        }

    @Test
    fun clearRejectsLateResultsAndInvalidatesPreviouslyCachedContent() =
        runBlocking {
            val calls = Calls()
            val started = CountDownLatch(1)
            val release = CountDownLatch(1)
            val renderer =
                MarkdownRenderer(2, 1024) { source ->
                    if (source == "late" && calls.count(source) == 0) {
                        started.countDown()
                        check(release.await(3, TimeUnit.SECONDS))
                    }
                    calls.parse(source)
                }
            renderer.render("cached")
            val stale = async(kotlinx.coroutines.Dispatchers.Default) { renderer.render("late") }
            try {
                assertTrue(started.await(3, TimeUnit.SECONDS))
                renderer.clear()
            } finally {
                release.countDown()
            }
            assertThrows(CancellationException::class.java) { runBlocking { stale.await() } }
            renderer.render("cached")
            renderer.render("late")
            assertEquals(2, calls.count("cached"))
            assertEquals(2, calls.count("late"))
        }

    @Test
    fun cancelledParserCannotPopulateTheCache() =
        runBlocking {
            val calls = Calls()
            val started = CountDownLatch(1)
            val release = CountDownLatch(1)
            val renderer =
                MarkdownRenderer(2, 1024) { source ->
                    started.countDown()
                    check(release.await(3, TimeUnit.SECONDS))
                    calls.parse(source)
                }
            val pending = async(kotlinx.coroutines.Dispatchers.Default) { renderer.render("cancelled") }
            try {
                assertTrue(started.await(3, TimeUnit.SECONDS))
                pending.cancel()
            } finally {
                release.countDown()
            }
            assertThrows(CancellationException::class.java) { runBlocking { pending.await() } }
            pending.join()
            renderer.render("cancelled")
            assertEquals(2, calls.count("cancelled"))
        }

    @Test
    fun independentScopesNeverShareCachedContentAndParsingRunsOffTheCaller() =
        runBlocking {
            val caller = Thread.currentThread()
            val calls = Calls()
            val parse = { source: String ->
                assertFalse(Thread.currentThread() === caller)
                calls.parse(source)
            }
            val first = MarkdownRenderer(2, 1024, parse)
            val second = MarkdownRenderer(2, 1024, parse)
            first.render("same")
            second.render("same")
            first.render("same")
            assertEquals(2, calls.count("same"))
        }

    private class Calls {
        private val counts = ConcurrentHashMap<String, AtomicInteger>()

        fun count(source: String) = counts[source]?.get() ?: 0

        fun parse(source: String) =
            MarkdownParser.parse(source).also {
                counts.computeIfAbsent(source) { AtomicInteger() }.incrementAndGet()
            }
    }
}
