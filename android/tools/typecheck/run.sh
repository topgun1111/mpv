#!/usr/bin/env bash
# Type-check the pure-Kotlin parts of the app WITHOUT Gradle / Android SDK / Maven (Debug Part 3).
# Covers: core/ (kotlinx.serialization stubbed) and every app file that does not use Compose, Media3 or OpenCV types
# (Diag, Safety minus its @Composable tail, Scanner, ScanService, PoseRunner, QnnSessions, VideoDecoder, Updater, SamEngine pose+sam).
# Needs: python3 (+ `pip install zstandard`), curl, a JRE. Downloads kotlinc (conda-forge) and android.jar (Sable/android-platforms) to $WORK.
# Expected result: "core OK", then errors ONLY in PointScanner.kt (it needs the excluded OpenCV classes RegionTracker, PointTracker, GrayStore). Any other file in the error list = a real error.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; ROOT="$HERE/../.."; WORK="${WORK:-/tmp/typecheck}"; mkdir -p "$WORK"; cd "$WORK"
if [ ! -x kc/out/bin/kotlinc ]; then
  curl -sSf -o kotlin.conda https://conda.anaconda.org/conda-forge/noarch/kotlin-2.1.21-hc364b38_0.conda
  mkdir -p kc && (cd kc && unzip -oq ../kotlin.conda && python3 -c "
import zstandard,tarfile,glob
tarfile.open(fileobj=zstandard.ZstdDecompressor().stream_reader(open(glob.glob('pkg-*.tar.zst')[0],'rb')),mode='r|').extractall('out')")
fi
[ -f android.jar ] || curl -sSf -o android.jar https://raw.githubusercontent.com/Sable/android-platforms/master/android-35/android.jar
export PATH="$WORK/kc/out/bin:$PATH" KOTLIN_HOME="$WORK/kc/out/libexec/kotlin"
A="$ROOT/app/src"; M="$A/main/kotlin/com/takipli/oynat"
# 1. core (serialization plugin output `serializer()` replaced by the stub in a temp copy)
rm -rf core && mkdir core && cp "$ROOT"/core/src/main/kotlin/com/takipli/oynat/core/*.kt core/
sed -i 's/serializer(), p)/kotlinx.serialization.serializer<CamPath>(), p)/; s/decodeFromString(serializer(), text)/decodeFromString(kotlinx.serialization.serializer<CamPath>(), text)/' core/Stabilize.kt
kotlinc -nowarn -jvm-target 17 -d core.jar "$HERE/ser.kt" "$HERE/json.kt" core/*.kt && echo "core OK"
# 2. app: R + BuildConfig stubs, UI stubs, then the non-Compose files
rm -rf app && mkdir -p app/pose app/sam
python3 - "$A" "$M" <<'P'
import re,glob,sys
from collections import defaultdict
A,M=sys.argv[1:3]; d=defaultdict(set)
for f in glob.glob(A+'/**/*.kt',recursive=True):
    for k,n in re.findall(r'\bR\.([a-z]+)\.([A-Za-z0-9_]+)',open(f).read()): d[k].add(n)
s="package com.takipli.oynat\nobject R {\n"+"".join(f"  object {k} {{\n"+"".join(f"    const val {n} = 0\n" for n in sorted(v))+"  }\n" for k,v in d.items())+"}\n"
s+='object BuildConfig { const val VERSION_NAME="1"; const val BUILD_NUMBER=1; const val VERSION_CODE=1; const val ENGINE="pose"; const val UPDATE_REPO="" }\n'
open('app/rbc.kt','w').write(s)
fa=open(M+'/FrameAnalyzer.kt').read().split('\n'); i=[k for k,l in enumerate(fa) if l.startswith('class FrameAnalysis(')][0]
open('app/ui_stub.kt','w').write("""package com.takipli.oynat
import android.graphics.Bitmap
import com.takipli.oynat.core.*
class MainActivity : android.app.Activity()
class ScanPreview(val t: Double, val bitmap: Bitmap, val overlay: PreviewOverlay)
const val PREVIEW_MIN_MS = 200L
fun previewBitmap(src: Bitmap): Bitmap = src
class OpenCvFlow : FlowTracker { companion object { val available = true }
  override fun match(prev: GrayImage, cur: GrayImage, mask: List<IntArray>): FlowMatches? = null }
"""+'\n'.join(fa[i:]))
t=open(M+'/SamBenchSection.kt').read().split('\n')
i=[k for k,l in enumerate(t) if l.startswith('/** One EdgeTAM graph')][0]; j=[k for k,l in enumerate(t) if l.startswith('@Composable')][0]
open('app/sambench_stub.kt','w').write("package com.takipli.oynat\nimport com.takipli.oynat.core.BenchStats\n"+'\n'.join(t[i:j]))
P
for f in Diag Scanner PoseRunner QnnSessions VideoDecoder ScanService PointScanner Updater SamPreviewTypes; do cp "$M/$f.kt" app/; done
n=$(grep -n '^@Composable' "$M/Safety.kt" | head -1 | cut -d: -f1)
head -n $((n-1)) "$M/Safety.kt" | grep -v 'androidx.compose' > app/Safety.kt
for fl in pose sam; do
  echo "=== flavor $fl"
  cp "$A/$fl/kotlin/com/takipli/oynat/SamEngine.kt" app/$fl/
  kotlinc -nowarn -jvm-target 17 -Xjava-source-roots="$HERE" -cp core.jar:android.jar -d app-$fl.jar "$HERE/coroutines.kt" "$HERE/flow.kt" app/*.kt app/$fl/*.kt 2>&1 | grep 'error:' | sed -E 's#^.*/app/##' || true
done
