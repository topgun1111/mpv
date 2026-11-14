package com.takipli.oynat.core

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.double
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** Part 10: person / joint / preset views and tap resolution against `golden/target_views.json` (Python reference). */
class ViewsTest {
    private fun res(name: String): JsonObject =
        Json.parseToJsonElement(checkNotNull(javaClass.getResource("/golden/$name.json")) { "missing $name" }.readText()).jsonObject

    private val scan = res("scan")
    private val fx = res("target_views")

    private fun docOf(samples: JsonArray): TrackDoc = Formats.parseTrack(
        JsonObject(
            mapOf(
                "version" to JsonPrimitive(2),
                "video" to JsonObject(mapOf("w" to scan.getValue("w"), "h" to scan.getValue("h"))),
                "samples" to samples,
            ),
        ).toString(),
    )

    private val base = docOf(scan.getValue("samples").jsonArray)

    private val gap: TrackDoc = run {
        val (from, to, id) = fx.getValue("docs").jsonObject.getValue("gap_ids").jsonArray.map { it.jsonPrimitive.int }
        base.copy(
            samples = base.samples.mapIndexed { i, s ->
                if (i !in from until to) s
                else s.copy(
                    d = s.d.filter { it[0].toInt() != id },
                    kp = s.kp?.filterKeys { it != id.toString() }?.ifEmpty { null },
                )
            },
        )
    }

    private fun cfgOf(name: String): Config = Formats.parseConfig(fx.getValue("cfgs").jsonObject.getValue(name).toString())

    @Test
    fun viewsMatchPython() {
        val cases = fx.getValue("cases").jsonArray.map { it.jsonObject }
        assertTrue(cases.size >= 20)
        for (c in cases) {
            val doc = if (c.getValue("doc").jsonPrimitive.content == "gap") gap else base
            val id = c.getValue("id").jsonPrimitive.int
            val arg = c.getValue("arg")
            val target = when (c.getValue("kind").jsonPrimitive.content) {
                "person" -> Target(id)
                "joint" -> Target(id, part = arg.jsonPrimitive.int)
                else -> Target(id, preset = arg.jsonPrimitive.content)
            }
            val label = "${c["doc"]} ${c["kind"]} id=$id arg=$arg cfg=${c["cfg"]}"
            val got = buildTargetViews(doc, target, cfgOf(c.getValue("cfg").jsonPrimitive.content))
            val exp = c.getValue("views").jsonArray.map { r -> r.jsonArray.map { it.jsonPrimitive.double } }
            assertEquals(exp.size, got.size, "keyframes: $label")
            for ((i, row) in exp.withIndex()) for (k in row.indices) assertEquals(row[k], got[i][k], 1e-9, "$label [$i][$k]")
        }
    }

    @Test
    fun tapsMatchPython() {
        for (c in fx.getValue("taps").jsonArray.map { it.jsonObject }) {
            val got = resolveTap(base, c.getValue("t").jsonPrimitive.double, c.getValue("x").jsonPrimitive.double, c.getValue("y").jsonPrimitive.double, Config())
            val e = c.getValue("result")
            if (e is JsonNull) assertNull(got, "tap $c") else {
                val r = e.jsonArray
                assertEquals(r[0].jsonPrimitive.int, got?.first, "tap id $c")
                assertEquals(r[1].let { if (it is JsonNull) null else it.jsonPrimitive.int }, got?.second, "tap joint $c")
            }
        }
    }

    @Test
    fun presetFallsBackToPersonSliceWithoutJointsAndRejectsUnknownNames() {
        val s = Sample(0.0, listOf(listOf(1.0, 0.2, 0.1, 0.4, 0.9, 0.9)))
        val doc = TrackDoc(2, VideoInfo("", 1000, 500), samples = listOf(s))
        val b = presetBoxes(doc, setOf(1), "left_leg", Config()).getValue(0)
        assertEquals(0.3, b[0], 1e-12) // person centre x
        assertEquals(0.1 + 0.8 * 0.75, b[1], 1e-12) // middle of the lower half
        assertEquals(0.2, b[2], 1e-12)
        assertEquals(0.4, b[3], 1e-12)
        assertFailsWith<IllegalArgumentException> { presetBoxes(doc, setOf(1), "elbow", Config()) }
        assertEquals(PRESETS.keys.size, 12)
    }
}
