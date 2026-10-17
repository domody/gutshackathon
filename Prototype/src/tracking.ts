import {
  FaceLandmarker,
  FilesetResolver,
  HandLandmarker,
  PoseLandmarker,
  type NormalizedLandmark,
} from '@mediapipe/tasks-vision';

export type TrackerKind = 'hand' | 'pose' | 'face';
export type TrackingResult = {
  landmarks: NormalizedLandmark[] | null;
  blendshapes?: Record<string, number>;
};

const WASM = 'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.22-rc.20250304/wasm';
const MODELS = {
  hand: 'https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task',
  pose: 'https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task',
  face: 'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task',
};

export class VisionTracker {
  private hand?: HandLandmarker;
  private pose?: PoseLandmarker;
  private face?: FaceLandmarker;
  kind: TrackerKind | null = null;

  async load(kind: TrackerKind) {
    this.close();
    const vision = await FilesetResolver.forVisionTasks(WASM);
    const baseOptions = { modelAssetPath: MODELS[kind], delegate: 'GPU' as const };
    if (kind === 'hand') {
      this.hand = await HandLandmarker.createFromOptions(vision, {
        baseOptions, runningMode: 'VIDEO', numHands: 1,
        minHandDetectionConfidence: 0.55, minTrackingConfidence: 0.5,
      });
    } else if (kind === 'pose') {
      this.pose = await PoseLandmarker.createFromOptions(vision, {
        baseOptions, runningMode: 'VIDEO', numPoses: 1,
        minPoseDetectionConfidence: 0.55, minTrackingConfidence: 0.5,
      });
    } else {
      this.face = await FaceLandmarker.createFromOptions(vision, {
        baseOptions, runningMode: 'VIDEO', numFaces: 1, outputFaceBlendshapes: true,
        minFaceDetectionConfidence: 0.55, minTrackingConfidence: 0.5,
      });
    }
    this.kind = kind;
  }

  detect(video: HTMLVideoElement, time: number): TrackingResult {
    if (this.hand) return { landmarks: this.hand.detectForVideo(video, time).landmarks[0] ?? null };
    if (this.pose) return { landmarks: this.pose.detectForVideo(video, time).landmarks[0] ?? null };
    if (this.face) {
      const result = this.face.detectForVideo(video, time);
      const blendshapes: Record<string, number> = {};
      for (const category of result.faceBlendshapes[0]?.categories ?? []) blendshapes[category.categoryName] = category.score;
      return { landmarks: result.faceLandmarks[0] ?? null, blendshapes };
    }
    return { landmarks: null };
  }

  close() {
    this.hand?.close(); this.pose?.close(); this.face?.close();
    this.hand = undefined; this.pose = undefined; this.face = undefined; this.kind = null;
  }
}
