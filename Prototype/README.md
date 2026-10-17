# GUTS Webcam Game Collection

A local-first collection of four playable webcam games. It uses MediaPipe Tasks Vision in the browser; camera frames are not uploaded and there is no backend.

## Launch

Requirements: Node.js 18+ and a current Chrome, Edge, or Safari browser with a webcam. The first run needs internet access to download MediaPipe model files.

```bash
npm install
npm run dev
```

Open the local URL printed by Vite (normally `http://localhost:5173`). Allow camera access when prompted. For a production build:

```bash
npm test
npm run build
npm run preview
```

Camera access requires `localhost` or HTTPS. Use bright, even front lighting and avoid backlighting.

## Prototypes and controls

### 1. Dalgona trace

- Sit roughly 60–90 cm from the camera with one full hand visible.
- Move the index fingertip to position the needle.
- Pinch thumb and index finger to carve; open them to reposition.
- Follow the entire outline. Revisiting the same area does not add progress.
- Tune sensitivity, smoothing, pinch thresholds, tolerance, and optional light assistance.
- The triangle is the default. A circle is available after the triangle via **Shape**.

### 2. Red light, green light

- Stand 1.5–2.5 m away with head, shoulders, elbows, and hands visible.
- Stand naturally and still, then choose **Calibrate neutral**.
- Alternate your arms to advance on green; become still on red.
- Tune motion sensitivity and stopping grace, or reset the short course at any time.

### 3. Tug of war

- Sit 50–80 cm away with your face clearly visible.
- Relax your face and choose **Capture neutral**.
- Make the exaggerated expression you want to use, then choose **Capture pull face**.
- Hold that expression to pull; relax to recover stamina.
- The score represents visible facial movement only. It does not measure force, strain, effort, or emotion.

### 4. Glass bridge

- Sit naturally 50–90 cm away with your full face visible.
- Look straight at the camera and choose **Set centre**.
- Move your head deliberately left or right. Return your head to the centre zone before the next choice.
- Choose **Preview route** for a three-second safe-route preview.

## Shared feedback

The mirrored preview aligns tracking coordinates with the image. Each prototype shows tracking state, inference time, game metrics, a short positioning guide, and a recognition event log. Tracking loss pauses gameplay. Switching prototypes keeps one camera stream alive and replaces the active MediaPipe tracker, so only the required model runs.

All calibration and reset actions can be repeated without refreshing. Debug buttons are setup aids only; normal gameplay inputs come from the webcam.

## Checks

The focused logic tests cover unique outline coverage, elapsed-time damage, pinch hysteresis, and side-step rearming:

```bash
npm test
```

## Known limitations and biggest uncertainties

- **Dalgona:** fingertip depth, hand scale, and laptop camera field of view may make one set of pinch thresholds feel different across users. The defaults need testing on several real webcams.
- **Red light, green light:** movement thresholds may need per-device tuning for seated players, loose clothing, low frame rates, and people with naturally animated posture.
- **Tug of war:** MediaPipe blendshape response varies with expression style, facial geometry, glasses, facial hair, and lighting; the two-step personal calibration reduces but does not remove this variance.
- **Glass bridge:** head movement is much easier to frame than full-body movement, but glasses, face occlusion, and users turning too far sideways may still interrupt tracking. The live centre gauge and centre rearm make the expected motion visible.
- Model assets and WASM are fetched from Google/jsDelivr on first load, so fully offline startup is not yet supported.
- Webcam recognition needs human testing on target MacBook and Windows gaming laptop hardware. Automated tests verify only the pure interaction rules, not recognition quality.
