# PC Android-style tracking workflow

The PC player now follows the same basic interaction as the Android app:

1. Launch mpv: the Tracker settings panel opens immediately.
2. Open a video: playback is paused so the user can configure tracking first.
3. Choose the target mode and, if needed, a body preset (head, torso, arm, leg, foot, hands).
4. Close the settings panel, then right-click the person/body region to select the target. In rectangle mode, right-drag to draw the target area.
5. Press Play: the offline video-processing scan starts. Pressing Play before selecting a target simply pauses again and explains what is missing.
6. When processing completes, the video rewinds and plays the computed camera path as a preview. Use File > Takip kamerası dışa aktar to render the MP4.

Body presets are passed to the offline processor with `--preset`. Non-person presets require pose/keypoint data; the CLI automatically enables pose scanning for point/rectangle selection when a configured pose model is present. If no pose model is installed, body-part framing cannot be generated; person tracking remains available.

The preview reuses the precomputed camera path. It does not run a second inference pass during preview, keeping preview and exported framing consistent.
