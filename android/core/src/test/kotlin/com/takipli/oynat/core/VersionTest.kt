package com.takipli.oynat.core

import kotlin.test.Test
import kotlin.test.assertEquals

class VersionTest {
    @Test
    fun versionCodeFollowsFormula() {
        assertEquals(10200, versionCode("1.2.0"))
        assertEquals(10203, versionCode("1.2.3\n"))
        assertEquals(20000, versionCode("2.0"))
        assertEquals(10200, versionCode("1.2.0-beta"))
        assertEquals(0, versionCode(""))
    }

    @Test
    fun coreModuleIsLinked() {
        assertEquals("ok", CoreInfo.label())
    }
}
