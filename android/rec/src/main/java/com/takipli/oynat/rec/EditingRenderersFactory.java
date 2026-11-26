package com.takipli.oynat.rec;

import android.content.Context;
import android.os.Handler;
import androidx.media3.common.util.UnstableApi;
import androidx.media3.exoplayer.DefaultRenderersFactory;
import androidx.media3.exoplayer.Renderer;
import androidx.media3.exoplayer.mediacodec.MediaCodecSelector;
import androidx.media3.exoplayer.video.MediaCodecVideoRenderer;
import androidx.media3.exoplayer.video.PlaybackVideoGraphWrapper;
import androidx.media3.exoplayer.video.VideoFrameReleaseControl;
import androidx.media3.exoplayer.video.VideoRendererEventListener;
import java.util.ArrayList;

/**
 * Media3 1.8.0's default graph disables its replayable cache. The editor needs
 * this cache to redraw the paused source frame with new shader uniforms.
 * Preserve the stock video renderer and all default non-video renderers.
 */
@UnstableApi
final class EditingRenderersFactory extends DefaultRenderersFactory {
    EditingRenderersFactory(Context context) {
        super(context);
    }

    @Override
    protected void buildVideoRenderers(
            Context context,
            int extensionRendererMode,
            MediaCodecSelector mediaCodecSelector,
            boolean enableDecoderFallback,
            Handler eventHandler,
            VideoRendererEventListener eventListener,
            long allowedVideoJoiningTimeMs,
            ArrayList<Renderer> out) {
        MediaCodecVideoRenderer.Builder builder = new MediaCodecVideoRenderer.Builder(context)
                .setCodecAdapterFactory(getCodecAdapterFactory())
                .setMediaCodecSelector(mediaCodecSelector)
                .setAllowedJoiningTimeMs(allowedVideoJoiningTimeMs)
                .setEnableDecoderFallback(enableDecoderFallback)
                .setEventHandler(eventHandler)
                .setEventListener(eventListener)
                .setMaxDroppedFramesToNotify(MAX_DROPPED_VIDEO_FRAME_COUNT_TO_NOTIFY);
        out.add(new MediaCodecVideoRenderer(builder) {
            @Override
            protected PlaybackVideoGraphWrapper createPlaybackVideoGraphWrapper(
                    Context context, VideoFrameReleaseControl videoFrameReleaseControl) {
                return new PlaybackVideoGraphWrapper.Builder(context, videoFrameReleaseControl)
                        .setEnablePlaylistMode(true)
                        .setEnableReplayableCache(true)
                        .setClock(getClock())
                        .build();
            }
        });
    }
}
