package com.takipli.oynat.core

// ---- Part 20: what the pick screen draws on the first frame (coloured body parts, joint dots, the chosen part).
// Everything goes through the same functions the scan and export use (`presetBoxes`, `resolvePick`), so what is
// highlighted before the scan is what gets followed. ----

/** Parts drawn on every person, in legend order (left/right = the subject's, COCO convention). */
val PART_GROUPS: List<String> = listOf("head", "torso", "left_arm", "right_arm", "left_leg", "right_leg", "left_foot", "right_foot")

/** Part colours as 0xRRGGBB; presets without an entry (person, legs, feet, hands) are drawn white. */
val PART_RGB: Map<String, Int> = mapOf(
    "head" to 0xFFC107, "torso" to 0x29B6F6,
    "left_arm" to 0x66BB6A, "right_arm" to 0xAB47BC,
    "left_leg" to 0xFF7043, "right_leg" to 0x5C6BC0,
    "left_foot" to 0xFFEE58, "right_foot" to 0xEC407A,
)

/** COCO-17 joint names (a tapped joint kept as a single-joint target is labelled with these). */
private val JOINT_NAMES = listOf(
    "nose", "left eye", "right eye", "left ear", "right ear", "left shoulder", "right shoulder", "left elbow",
    "right elbow", "left wrist", "right wrist", "left hip", "right hip", "left knee", "right knee", "left ankle", "right ankle",
)

/**
 * One person found on the pick frame. `box` and every part box are `[x1, y1, x2, y2]` normalized to 0..1; `joints` =
 * confident joints as (joint index, x, y) normalized.
 */
class PickPerson(val id: Int, val box: DoubleArray, val parts: Map<String, DoubleArray>, val joints: List<Triple<Int, Double, Double>>)

/** What a pick would follow: `target` as the scan will resolve it, `box` = its region `[x1, y1, x2, y2]` (null when it has none here). */
class PickHighlight(val target: Target, val box: DoubleArray?)

private fun unit(v: Double) = v.coerceIn(0.0, 1.0)

/** `[cx, cy, w, h]` (as `presetBoxes` returns) -> clamped corners `[x1, y1, x2, y2]`. */
private fun corners(b: DoubleArray) =
    doubleArrayOf(unit(b[0] - b[2] / 2), unit(b[1] - b[3] / 2), unit(b[0] + b[2] / 2), unit(b[1] + b[3] / 2))

/**
 * A one-sample doc from the people the pose model found on the shown frame (`w` x `h` px): IDs 1..n in pose order,
 * keypoints normalized. The same shape the scan writes, so `resolvePick` and `presetBoxes` work on it unchanged.
 */
fun firstFrameDoc(poses: List<Pose>, w: Int, h: Int, t: Double): TrackDoc {
    val fw = w.coerceAtLeast(1).toDouble(); val fh = h.coerceAtLeast(1).toDouble()
    val d = ArrayList<List<Double>>()
    val kp = LinkedHashMap<String, List<Double>>()
    poses.forEachIndexed { i, p ->
        val id = i + 1
        d.add(listOf(id.toDouble(), p.bbox.x1 / fw, p.bbox.y1 / fh, p.bbox.x2 / fw, p.bbox.y2 / fh, p.score))
        if (p.count >= N_KPT) kp[id.toString()] = (0 until N_KPT).flatMap { k -> listOf(p.x(k) / fw, p.y(k) / fh, p.conf(k)) }
    }
    return TrackDoc(version = 2, video = VideoInfo(w = w, h = h), samples = listOf(Sample(t, d = d, kp = kp)))
}

/** Region of `preset` on every person of a first-frame doc: person ID -> `[x1, y1, x2, y2]`. Unknown preset -> empty. */
fun presetRegions(doc: TrackDoc, preset: String, cfg: Config): Map<Int, DoubleArray> {
    if (preset !in PRESETS) return emptyMap()
    val s = doc.samples.firstOrNull() ?: return emptyMap()
    val out = LinkedHashMap<Int, DoubleArray>()
    for (row in s.d) {
        val id = row[0].toInt()
        presetBoxes(doc, setOf(id), preset, cfg)[0]?.let { out[id] = corners(it) }
    }
    return out
}

/** Everyone on the first frame with their coloured part regions and joint dots. */
fun pickPersons(doc: TrackDoc, cfg: Config): List<PickPerson> {
    val s = doc.samples.firstOrNull() ?: return emptyList()
    val byGroup = PART_GROUPS.associateWith { presetRegions(doc, it, cfg) }
    return s.d.map { row ->
        val id = row[0].toInt()
        val parts = LinkedHashMap<String, DoubleArray>()
        for (g in PART_GROUPS) byGroup.getValue(g)[id]?.let { parts[g] = it }
        val kp = s.kp?.get(id.toString())
        val joints = ArrayList<Triple<Int, Double, Double>>()
        if (kp != null && kp.size >= 3 * N_KPT) {
            for (k in 0 until N_KPT) if (kp[3 * k + 2] >= cfg.kpMinConf) joints.add(Triple(k, kp[3 * k], kp[3 * k + 1]))
        }
        PickPerson(id, doubleArrayOf(row[1], row[2], row[3], row[4]), parts, joints)
    }
}

/**
 * A tap inside a drawn part -> (person ID, part). The smallest box wins, so a foot beats the leg and an arm beats the
 * torso; a tap outside every part returns null (the person under it, if any, is then the whole person).
 */
fun partHit(persons: List<PickPerson>, nx: Double, ny: Double): Pair<Int, String>? {
    var bestId = -1; var bestPart = ""; var bestArea = Double.MAX_VALUE
    for (p in persons) for ((g, b) in p.parts) {
        if (nx < b[0] || nx > b[2] || ny < b[1] || ny > b[3]) continue
        val area = (b[2] - b[0]) * (b[3] - b[1])
        if (area < bestArea) { bestArea = area; bestId = p.id; bestPart = g }
    }
    return if (bestId < 0) null else bestId to bestPart
}

/**
 * What `pick` would follow, resolved exactly like the scan does (`resolvePick`) on the first-frame doc, plus the region
 * of that target. Null when nobody is at the picked point.
 */
fun highlightPick(doc: TrackDoc, pick: TargetPick, cfg: Config): PickHighlight? {
    val target = resolvePick(doc, pick, cfg) ?: return null
    val ids = setOf(target.id)
    val boxes = when {
        target.preset != null -> presetBoxes(doc, ids, target.preset, cfg)
        target.part != null -> jointBoxes(doc, ids, target.part, cfg)
        else -> personBoxes(doc, ids)
    }
    return PickHighlight(target, boxes[0]?.let { corners(it) })
}

/** Short name of a target for the screen: the preset (`left_arm` -> "left arm"), a single joint, or the whole person. */
fun partLabel(t: Target): String = when {
    t.preset != null -> t.preset.replace('_', ' ')
    t.part != null -> JOINT_NAMES.getOrElse(t.part) { "joint ${t.part}" }
    else -> "whole person"
}
