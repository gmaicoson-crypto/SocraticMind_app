package com.gmaicoson.socraticmind.chat

import com.gmaicoson.socraticmind.auth.SessionState
import com.gmaicoson.socraticmind.network.HttpFailure
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.yield
import org.junit.jupiter.api.Assertions.assertArrayEquals
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNotNull
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import java.io.IOException

class ChatAvatarControllerTest {
    private val preset = ChatAvatarResource(ChatAvatarResource.presets(ChatMode.NORMAL)[1])

    @Test fun `preset selection supports empty conversations and rejects stale picker results`(): Unit =
        runBlocking {
            withAvatar(this) { h ->
                h.login()
                val old = h.picker()
                h.model.dismiss()
                val target = ChatTarget("new-local")
                h.base.history.model
                    .openConversation(target)
                h.base.history
                    .messages()
                    .succeed(emptyList())
                h.base.turn.select(target)
                val picker = h.picker()
                h.model.selectPreset(old, preset)
                h.model.selectPreset(picker, ChatAvatarResource.default(ChatMode.SOCRATIC))
                assertEquals(0, h.gateway.count)
                h.model.selectPreset(picker, preset)
                val call = next(h.gateway.calls)
                assertEquals("delete", call.kind)
                assertEquals("new-local", call.sessionId)
                assertEquals(preset, h.store.values[1]?.get("new-local"))
                call.response.complete(null)
                h.idle()
                assertEquals(
                    preset,
                    h.model.state.value
                        .resource(target),
                )
            }
        }

    @Test fun `upload snapshots data and holds the shared mutation gate`(): Unit =
        runBlocking {
            withAvatar(this) { h ->
                h.login()
                val picker = h.picker()
                val bytes = byteArrayOf(1, 2, 3)
                h.model.upload(picker, bytes, AvatarImageFormat.PNG)
                bytes[0] = 9
                h.model.upload(picker, bytes, AvatarImageFormat.PNG)
                val call = next(h.gateway.calls)
                assertArrayEquals(byteArrayOf(1, 2, 3), call.bytes)
                assertFalse(h.base.turn.state.value.editable)
                h.base.turn.send("标准")
                h.base.model.deleteSession("main")
                assertNull(h.base.model.state.value.dialog)
                assertTrue(
                    h.base.turnGateway.streams
                        .tryReceive()
                        .isFailure,
                )
                call.response.complete(uploadedAvatar())
                h.idle()
                assertEquals(uploadedAvatar(), h.store.values[1]?.get("main"))
                assertEquals(1, h.gateway.count)
                assertTrue(h.base.turn.state.value.editable)
                assertEquals("未发送的草稿", h.base.turn.state.value.draft)
            }
        }

    @Test fun `failed local save retains preview and retries without uploading again`(): Unit =
        runBlocking {
            withAvatar(this) { h ->
                h.login()
                val picker = h.picker()
                h.store.writeFailure = true
                h.model.upload(picker, byteArrayOf(1), AvatarImageFormat.PNG)
                next(h.gateway.calls).response.complete(uploadedAvatar())
                h.idle()
                assertNotNull(h.model.state.value.pendingSave)
                assertEquals(
                    uploadedAvatar(),
                    h.model.state.value
                        .resource(picker.target),
                )
                h.model.dismiss()
                h.model.open(picker.target)
                assertNull(h.model.state.value.picker)
                h.store.writeFailure = false
                h.model.retrySave()
                h.idle()
                assertNull(h.model.state.value.pendingSave)
                assertEquals(uploadedAvatar(), h.store.values[1]?.get("main"))
                assertEquals(1, h.gateway.count)
            }
        }

    @Test fun `save retry recognizes a write completed before readback failure`(): Unit =
        runBlocking {
            withAvatar(this) { h ->
                h.login()
                h.store.failAfterWrite = true
                h.model.upload(h.picker(), byteArrayOf(1), AvatarImageFormat.PNG)
                next(h.gateway.calls).response.complete(uploadedAvatar())
                h.idle()
                assertNotNull(h.model.state.value.pendingSave)
                h.model.retrySave()
                h.idle()
                assertNull(h.model.state.value.pendingSave)
                assertEquals(1, h.store.writes)
                assertEquals(1, h.gateway.count)
            }
        }

    @Test fun `preset cleanup occurs after saving and failure does not roll back selection`(): Unit =
        runBlocking {
            withAvatar(this) { h ->
                h.login()
                h.store.writeFailure = true
                h.model.selectPreset(h.picker(), preset)
                h.idle()
                assertEquals(0, h.gateway.count)
                h.store.writeFailure = false
                h.model.retrySave()
                val cleanup = next(h.gateway.calls)
                assertEquals(preset, h.store.values[1]?.get("main"))
                cleanup.response.completeExceptionally(IOException("synthetic lost response"))
                h.idle()
                assertEquals(preset, h.model.state.value.choices["main"])
                assertNull(h.model.state.value.pendingSave)
                assertTrue(checkNotNull(h.model.state.value.notice).contains("已保存"))
                h.model.selectPreset(h.picker(), null)
                next(h.gateway.calls).response.complete(null)
                h.idle()
                assertNull(h.store.values[1]?.get("main"))
            }
        }

    @Test fun `corrupt storage blocks changes until an explicit reload succeeds`(): Unit =
        runBlocking {
            withAvatar(this) { h ->
                h.store.readFailure = true
                h.login()
                h.model.open(checkNotNull(h.base.turn.state.value.target))
                assertFalse(h.model.state.value.loaded)
                assertNull(h.model.state.value.picker)
                assertEquals(0, h.store.writes)
                h.store.readFailure = false
                h.model.reload()
                h.idle()
                assertTrue(h.model.state.value.loaded)
            }
        }

    @Test fun `unknown upload is not replayed or treated as a successful selection`(): Unit =
        runBlocking {
            withAvatar(this) { h ->
                h.login()
                h.model.upload(h.picker(), byteArrayOf(1), AvatarImageFormat.PNG)
                next(h.gateway.calls).response.completeExceptionally(IOException("lost response"))
                h.idle()
                assertTrue(checkNotNull(h.model.state.value.notice).contains("未确认"))
                assertEquals(1, h.gateway.count)
                assertEquals(0, h.store.writes)
                h.model.retrySave()
                assertEquals(1, h.gateway.count)
            }
        }

    @Test fun `old upload cannot write after account change or release a new lease`(): Unit =
        runBlocking {
            withAvatar(this) { h ->
                h.login()
                h.model.upload(h.picker(), byteArrayOf(1), AvatarImageFormat.PNG)
                val old = next(h.gateway.calls)
                h.login(2)
                h.model.upload(h.picker(), byteArrayOf(2), AvatarImageFormat.PNG)
                val newer = next(h.gateway.calls)
                old.response.complete(uploadedAvatar())
                awaitHistory { old.completed.isCompleted }
                yield()
                assertTrue(h.model.state.value.busy)
                assertFalse(h.base.turn.state.value.editable)
                assertEquals(0, h.store.writes)
                newer.response.complete(uploadedAvatar(2))
                h.idle()
                assertNull(h.store.values[1])
                assertEquals(uploadedAvatar(2), h.store.values[2]?.get("main"))
            }
        }

    @Test fun `current unauthorized upload clears state and late unauthorized cannot sign out next login`(): Unit =
        runBlocking {
            withAvatar(this) { h ->
                h.login()
                h.model.upload(h.picker(), byteArrayOf(1), AvatarImageFormat.PNG)
                next(h.gateway.calls).response.completeExceptionally(HttpFailure(401, null, "expired", null))
                awaitHistory { h.model.state.value.account == null }
                assertTrue(h.base.session.state.value is SessionState.SignedOut)
                h.login()
                h.model.upload(h.picker(), byteArrayOf(1), AvatarImageFormat.PNG)
                val old = next(h.gateway.calls)
                h.login()
                old.response.completeExceptionally(HttpFailure(401, null, "expired", null))
                awaitHistory { old.completed.isCompleted }
                yield()
                assertTrue(h.base.session.state.value is SessionState.SignedIn)
                assertNotNull(h.model.state.value.account)
            }
        }

    @Test fun `conflicting save preserves the other selection and discard reloads it`(): Unit =
        runBlocking {
            withAvatar(this) { h ->
                h.login()
                val picker = h.picker()
                val other = ChatAvatarResource.default(ChatMode.NORMAL)
                h.store.values[1] = mapOf("main" to other)
                h.model.selectPreset(picker, preset)
                h.idle()
                assertNotNull(h.model.state.value.pendingSave)
                assertEquals(other, h.store.values[1]?.get("main"))
                assertEquals(0, h.gateway.count)
                h.model.discardPendingSave()
                h.idle()
                assertNull(h.model.state.value.pendingSave)
                assertEquals(other, h.model.state.value.choices["main"])
            }
        }

    @Test fun `confirmed deletion removes only its selection and cleanup failure keeps deletion successful`(): Unit =
        runBlocking {
            for (fail in listOf(false, true)) {
                withAvatar(this) { h ->
                    h.store.values[1] = mapOf("main" to preset, "other" to preset)
                    h.login()
                    h.store.writeFailure = fail
                    h.base.model.deleteSession("main")
                    h.base.model.confirm()
                    next(h.base.gateway.calls).response.complete(null)
                    awaitHistory { !h.base.model.state.value.busy }
                    assertNull(h.base.history.model.state.value.selected)
                    assertTrue(h.base.turn.state.value.editable)
                    assertNull(h.model.state.value.choices["main"])
                    assertEquals(preset, h.model.state.value.choices["other"])
                    assertEquals(if (fail) preset else null, h.store.values[1]?.get("main"))
                    assertEquals(fail, h.base.model.state.value.notice != null)
                }
            }
        }

    @Test fun `selection survives logout and keeps visually equal session identifiers separate`(): Unit =
        runBlocking {
            withAvatar(this) { h ->
                h.store.values[1] = mapOf("café" to preset, "cafe\u0301" to ChatAvatarResource.default(ChatMode.NORMAL))
                h.login()
                assertEquals(
                    preset,
                    h.model.state.value
                        .resource(ChatTarget("café")),
                )
                assertEquals(
                    ChatAvatarResource.default(ChatMode.NORMAL),
                    h.model.state.value
                        .resource(ChatTarget("cafe\u0301")),
                )
                h.login(2)
                assertTrue(
                    h.model.state.value.choices
                        .isEmpty(),
                )
                h.login()
                assertEquals(2, h.model.state.value.choices.size)
            }
        }

    @Test fun `late initial read cannot leak the previous account choices`(): Unit =
        runBlocking {
            withAvatar(this) { h ->
                h.base.login()
                h.store.values[1] = mapOf("main" to preset)
                val gate = CompletableDeferred<Unit>()
                h.store.readGate = gate
                h.model.bindAccount(h.base.session.state.value)
                assertEquals(1L, next(h.store.reads))
                h.model.clear()
                h.store.readGate = null
                h.login(2)
                gate.complete(Unit)
                yield()
                assertEquals(
                    2L,
                    h.model.state.value.account
                        ?.userId,
                )
                assertTrue(
                    h.model.state.value.choices
                        .isEmpty(),
                )
            }
        }

    @Test fun `deletion fences a pending initial avatar read`(): Unit =
        runBlocking {
            withAvatar(this) { h ->
                h.base.login()
                h.store.values[1] = mapOf("main" to preset)
                val gate = CompletableDeferred<Unit>()
                h.store.readGate = gate
                h.model.bindAccount(h.base.session.state.value)
                next(h.store.reads)
                h.store.readGate = null
                h.base.model.deleteSession("main")
                h.base.model.confirm()
                next(h.base.gateway.calls).response.complete(null)
                awaitHistory { !h.base.model.state.value.busy }
                gate.complete(Unit)
                awaitHistory { h.store.completedReads == 2 }
                yield()
                assertTrue(h.model.state.value.loaded)
                assertFalse(h.model.state.value.busy)
                assertTrue(
                    h.model.state.value.choices
                        .isEmpty(),
                )
                assertTrue(
                    h.store.values[1]
                        .orEmpty()
                        .isEmpty(),
                )
            }
        }

    @Test fun `invalid upload input and foreign returned resource never become a selection`(): Unit =
        runBlocking {
            withAvatar(this) { h ->
                h.login()
                val picker = h.picker()
                h.model.upload(picker, byteArrayOf(), AvatarImageFormat.PNG)
                assertEquals(0, h.gateway.count)
                h.model.upload(picker, byteArrayOf(1), AvatarImageFormat.PNG)
                next(h.gateway.calls).response.complete(uploadedAvatar(2))
                h.idle()
                assertEquals(0, h.store.writes)
                assertNull(h.model.state.value.pendingSave)
            }
        }
}
