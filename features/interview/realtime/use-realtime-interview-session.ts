"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ConnectionState,
  LocalTrackPublication,
  Room,
  RoomEvent,
  Track,
} from "livekit-client";
import { apiService } from "@/services/api-service";

export type RealtimeRound = "technical" | "hr";
export type CaptureMode = "idle" | "consent" | "answer";
export type MediaEventType =
  | "mic_muted"
  | "mic_unmuted"
  | "mic_unavailable"
  | "mic_stopped"
  | "mic_signal_paused"
  | "mic_signal_resumed"
  | "camera_off"
  | "camera_on"
  | "camera_unavailable"
  | "camera_stopped"
  | "camera_muted"
  | "camera_unmuted"
  | "media_state"
  | "livekit_connected"
  | "livekit_disconnected"
  | "livekit_error"
  | "transcription_connected"
  | "transcription_unavailable"
  | "transcription_error";

type LiveKitTokenResponse = {
  enabled: boolean;
  reason?: string;
  serverUrl?: string;
  token?: string;
  room?: string;
  identity?: string;
  expiresAt?: number;
};

type TranscriptionMessage = {
  event?: string;
  text?: string;
  confidence?: number | null;
  reason?: string;
  error?: string;
  provider?: string;
  model?: string;
  language?: string;
};

type TranscriptionMode = "deepgram" | "browser-fallback" | "unavailable";

type SpeechRecognitionLike = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  onresult: ((event: any) => void) | null;
  onstart: (() => void) | null;
  onaudiostart: (() => void) | null;
  onspeechstart: (() => void) | null;
  onspeechend: (() => void) | null;
  onnomatch: (() => void) | null;
  onerror: ((event: any) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
  abort?: () => void;
};

type UseRealtimeInterviewSessionOptions = {
  interviewId: string | null;
  round: RealtimeRound;
  previewActive: boolean;
  callActive: boolean;
  captureMode: CaptureMode;
  botSpeaking: boolean;
  language: string;
  onFinalTranscript: (text: string, confidence: number) => void | Promise<void>;
  onPartialTranscript?: (text: string) => void;
  onMediaEvent?: (event: MediaEventType, metadata?: Record<string, unknown>) => void;
};

type MediaConstraintsOptions = {
  camera: boolean;
  microphone: boolean;
  cameraDeviceId?: string | null;
  microphoneDeviceId?: string | null;
};

const DEEPGRAM_KEEPALIVE_MS = 4500;
const DEEPGRAM_MAX_RECONNECT_ATTEMPTS = 6;
const DEEPGRAM_RECONNECT_BASE_MS = 500;
const MICROPHONE_SIGNAL_PAUSE_GRACE_MS = 6000;

function getSpeechRecognitionCtor() {
  if (typeof window === "undefined") return null;
  return (
    (window as typeof window & { SpeechRecognition?: any; webkitSpeechRecognition?: any }).SpeechRecognition ||
    (window as typeof window & { SpeechRecognition?: any; webkitSpeechRecognition?: any }).webkitSpeechRecognition ||
    null
  );
}

function hasBrowserSpeechFallback() {
  return Boolean(getSpeechRecognitionCtor());
}

function getAudioMimeType() {
  if (typeof window === "undefined" || typeof MediaRecorder === "undefined") return "";
  const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus"];
  return candidates.find((type) => MediaRecorder.isTypeSupported(type)) || "";
}

function mediaConstraints(options: MediaConstraintsOptions): MediaStreamConstraints {
  return {
    video: options.camera
      ? {
          facingMode: "user",
          deviceId: options.cameraDeviceId ? { exact: options.cameraDeviceId } : undefined,
          width: { ideal: 1280 },
          height: { ideal: 720 },
        }
      : false,
    audio: options.microphone
      ? {
          deviceId: options.microphoneDeviceId ? { exact: options.microphoneDeviceId } : undefined,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        }
      : false,
  };
}

function isTrackUsable(track?: MediaStreamTrack | null) {
  return Boolean(track && track.readyState === "live" && track.enabled);
}

function transcriptSocketUrl(interviewId: string, round: RealtimeRound) {
  const url = new URL(apiService.baseURL);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = `/api/realtime/ws/interviews/${interviewId}/rounds/${round}/transcript`;
  const token = apiService.getToken();
  if (token) url.searchParams.set("token", token);
  return url.toString();
}

async function requestUserMedia(options: MediaConstraintsOptions) {
  if (typeof navigator === "undefined" || !navigator.mediaDevices?.getUserMedia) {
    throw new Error("Camera and microphone access is not available in this browser context.");
  }
  return navigator.mediaDevices.getUserMedia(mediaConstraints(options));
}

function stopStream(stream: MediaStream | null) {
  stream?.getTracks().forEach((track) => track.stop());
}

function removeExistingTracks(stream: MediaStream, kind: "audio" | "video") {
  const tracks = kind === "audio" ? stream.getAudioTracks() : stream.getVideoTracks();
  tracks.forEach((track) => {
    stream.removeTrack(track);
    track.stop();
  });
}

export function useRealtimeInterviewSession({
  interviewId,
  round,
  previewActive,
  callActive,
  captureMode,
  botSpeaking,
  language,
  onFinalTranscript,
  onPartialTranscript,
  onMediaEvent,
}: UseRealtimeInterviewSessionOptions) {
  const previewStreamRef = useRef<MediaStream | null>(null);
  const activeStreamRef = useRef<MediaStream | null>(null);
  const audioContextCleanupRef = useRef<(() => void) | null>(null);
  const transcriptSocketRef = useRef<WebSocket | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const browserRecognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const liveKitRoomRef = useRef<Room | null>(null);
  const liveKitPublicationRef = useRef<LocalTrackPublication | null>(null);
  const liveKitMicCloneRef = useRef<MediaStreamTrack | null>(null);
  const signalPauseTimerRef = useRef<number | null>(null);
  const micSignalPausedRef = useRef(false);
  const micRecoveryTimerRef = useRef<number | null>(null);
  const micRecoveryInFlightRef = useRef(false);
  const enableMicRef = useRef<(enabled: boolean) => Promise<void>>(async () => undefined);
  const startBrowserFallbackRef = useRef<() => void>(() => undefined);
  const connectTranscriptionRef = useRef<() => void>(() => undefined);
  const transcriptionKeepAliveRef = useRef<number | null>(null);
  const transcriptionReconnectTimerRef = useRef<number | null>(null);
  const deepgramReconnectAttemptsRef = useRef(0);
  const manualTranscriptionCloseRef = useRef(false);
  const transcriptionModeRef = useRef<TranscriptionMode>("unavailable");
  const captureModeRef = useRef<CaptureMode>(captureMode);
  const botSpeakingRef = useRef(botSpeaking);
  const callActiveRef = useRef(callActive);
  const micEnabledRef = useRef(true);
  const cameraEnabledRef = useRef(true);
  const onFinalTranscriptRef = useRef(onFinalTranscript);
  const onPartialTranscriptRef = useRef(onPartialTranscript);
  const onMediaEventRef = useRef(onMediaEvent);
  const selectedAudioDeviceIdRef = useRef<string | null>(null);
  const selectedVideoDeviceIdRef = useRef<string | null>(null);

  const [previewStream, setPreviewStream] = useState<MediaStream | null>(null);
  const [activeStream, setActiveStream] = useState<MediaStream | null>(null);
  const [cameraEnabled, setCameraEnabledState] = useState(true);
  const [micEnabled, setMicEnabledState] = useState(true);
  const [cameraDeviceReady, setCameraDeviceReady] = useState(false);
  const [micDeviceReady, setMicDeviceReady] = useState(false);
  const [micSignalPaused, setMicSignalPaused] = useState(false);
  const [audioLevel, setAudioLevel] = useState(0);
  const [userSpeaking, setUserSpeaking] = useState(false);
  const [mediaError, setMediaError] = useState("");
  const [speechError, setSpeechError] = useState("");
  const [speechStatus, setSpeechStatus] = useState("Mic is idle");
  const [isListening, setIsListening] = useState(false);
  const [partialTranscript, setPartialTranscript] = useState("");
  const [audioInputs, setAudioInputs] = useState<MediaDeviceInfo[]>([]);
  const [videoInputs, setVideoInputs] = useState<MediaDeviceInfo[]>([]);
  const [selectedAudioDeviceId, setSelectedAudioDeviceId] = useState<string | null>(null);
  const [selectedVideoDeviceId, setSelectedVideoDeviceId] = useState<string | null>(null);
  const [liveKitRoom, setLiveKitRoom] = useState<Room | null>(null);
  const [liveKitToken, setLiveKitToken] = useState<string | undefined>();
  const [liveKitServerUrl, setLiveKitServerUrl] = useState<string | undefined>();
  const [liveKitEnabled, setLiveKitEnabled] = useState(false);
  const [liveKitConnected, setLiveKitConnected] = useState(false);
  const [liveKitState, setLiveKitState] = useState<ConnectionState>(ConnectionState.Disconnected);
  const [liveKitReason, setLiveKitReason] = useState("");
  const [transcriptionMode, setTranscriptionModeState] = useState<TranscriptionMode>("unavailable");
  const [transcriptionConnected, setTranscriptionConnected] = useState(false);

  const setTranscriptionMode = useCallback((mode: TranscriptionMode) => {
    transcriptionModeRef.current = mode;
    setTranscriptionModeState(mode);
  }, []);

  const canCapture = useMemo(
    () =>
      callActive &&
      captureMode !== "idle" &&
      !botSpeaking &&
      micEnabled &&
      micDeviceReady,
    [botSpeaking, callActive, captureMode, micDeviceReady, micEnabled]
  );
  const canCaptureRef = useRef(canCapture);

  useEffect(() => {
    canCaptureRef.current = canCapture;
  }, [canCapture]);

  useEffect(() => {
    captureModeRef.current = captureMode;
  }, [captureMode]);

  useEffect(() => {
    botSpeakingRef.current = botSpeaking;
  }, [botSpeaking]);

  useEffect(() => {
    callActiveRef.current = callActive;
  }, [callActive]);

  useEffect(() => {
    micEnabledRef.current = micEnabled;
  }, [micEnabled]);

  useEffect(() => {
    cameraEnabledRef.current = cameraEnabled;
  }, [cameraEnabled]);

  useEffect(() => {
    onFinalTranscriptRef.current = onFinalTranscript;
  }, [onFinalTranscript]);

  useEffect(() => {
    onPartialTranscriptRef.current = onPartialTranscript;
  }, [onPartialTranscript]);

  useEffect(() => {
    onMediaEventRef.current = onMediaEvent;
  }, [onMediaEvent]);

  const emitMediaEvent = useCallback((event: MediaEventType, metadata: Record<string, unknown> = {}) => {
    onMediaEventRef.current?.(event, metadata);
  }, []);

  const passiveSpeechStatus = useCallback(() => {
    if (botSpeakingRef.current) return "Bot speaking";
    if (!micEnabledRef.current) return "Mic muted";
    if (captureModeRef.current === "idle") return "Mic is idle";
    return "Mic ready";
  }, []);

  const updateTrackReadiness = useCallback((stream: MediaStream | null = activeStreamRef.current || previewStreamRef.current) => {
    const audioTrack = stream?.getAudioTracks()[0] || null;
    const videoTrack = stream?.getVideoTracks()[0] || null;
    const micReady = micEnabledRef.current && isTrackUsable(audioTrack);
    const cameraReady = cameraEnabledRef.current && isTrackUsable(videoTrack);
    setMicDeviceReady(micReady);
    setCameraDeviceReady(cameraReady);
    if (!micReady) {
      setAudioLevel(0);
      setUserSpeaking(false);
    }
    return { audioTrack, videoTrack, micReady, cameraReady };
  }, []);

  const refreshDevices = useCallback(async () => {
    if (typeof navigator === "undefined" || !navigator.mediaDevices?.enumerateDevices) return;
    try {
      const devices = await navigator.mediaDevices.enumerateDevices();
      setAudioInputs(devices.filter((device) => device.kind === "audioinput"));
      setVideoInputs(devices.filter((device) => device.kind === "videoinput"));
    } catch {
      // Device labels are optional until permissions are granted.
    }
  }, []);

  useEffect(() => {
    void refreshDevices();
    if (typeof navigator === "undefined" || !navigator.mediaDevices?.addEventListener) return;
    navigator.mediaDevices.addEventListener("devicechange", refreshDevices);
    return () => navigator.mediaDevices.removeEventListener("devicechange", refreshDevices);
  }, [refreshDevices]);

  const stopAudioMeter = useCallback(() => {
    audioContextCleanupRef.current?.();
    audioContextCleanupRef.current = null;
    setAudioLevel(0);
    setUserSpeaking(false);
  }, []);

  const startAudioMeter = useCallback(
    (stream: MediaStream | null) => {
      stopAudioMeter();
      const track = stream?.getAudioTracks()[0];
      if (!track || typeof window === "undefined") {
        updateTrackReadiness(stream);
        return;
      }
      const AudioContextCtor =
        window.AudioContext || (window as typeof window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      if (!AudioContextCtor) {
        updateTrackReadiness(stream);
        return;
      }

      try {
        const audioContext = new AudioContextCtor();
        void audioContext.resume().catch(() => undefined);
        const analyser = audioContext.createAnalyser();
        analyser.fftSize = 256;
        const source = audioContext.createMediaStreamSource(new MediaStream([track]));
        source.connect(analyser);
        const samples = new Uint8Array(analyser.frequencyBinCount);
        const interval = window.setInterval(() => {
          const { micReady } = updateTrackReadiness(stream);
          if (!micReady) return;
          analyser.getByteTimeDomainData(samples);
          let total = 0;
          samples.forEach((sample) => {
            const normalized = (sample - 128) / 128;
            total += normalized * normalized;
          });
          const level = Math.min(1, Math.sqrt(total / samples.length) * 4);
          if (level > 0.03 && micSignalPausedRef.current) {
            micSignalPausedRef.current = false;
            setMicSignalPaused(false);
            setSpeechError("");
            setSpeechStatus("Mic signal restored");
            emitMediaEvent("mic_signal_resumed", { source: "audio_level" });
          }
          setAudioLevel(level);
          setUserSpeaking(level > 0.08);
        }, 160);
        audioContextCleanupRef.current = () => {
          window.clearInterval(interval);
          source.disconnect();
          analyser.disconnect();
          audioContext.close().catch(() => undefined);
        };
      } catch {
        updateTrackReadiness(stream);
      }
    },
    [emitMediaEvent, stopAudioMeter, updateTrackReadiness]
  );

  const stopMediaRecorder = useCallback(() => {
    const recorder = mediaRecorderRef.current;
    mediaRecorderRef.current = null;
    if (recorder && recorder.state !== "inactive") {
      try {
        recorder.stop();
      } catch {
        // The browser may already have stopped it when the track changed.
      }
    }
  }, []);

  const stopBrowserRecognition = useCallback((abort = false) => {
    const recognition = browserRecognitionRef.current;
    browserRecognitionRef.current = null;
    if (!recognition) return;
    try {
      if (abort && recognition.abort) {
        recognition.abort();
      } else {
        recognition.stop();
      }
    } catch {
      // Recognition throws if already stopped.
    }
  }, []);

  const clearTranscriptionKeepAlive = useCallback(() => {
    if (typeof window === "undefined" || transcriptionKeepAliveRef.current === null) return;
    window.clearInterval(transcriptionKeepAliveRef.current);
    transcriptionKeepAliveRef.current = null;
  }, []);

  const startTranscriptionKeepAlive = useCallback(() => {
    if (typeof window === "undefined") return;
    clearTranscriptionKeepAlive();
    transcriptionKeepAliveRef.current = window.setInterval(() => {
      const socket = transcriptSocketRef.current;
      if (!socket || socket.readyState !== WebSocket.OPEN) return;
      try {
        socket.send(JSON.stringify({ type: "keepalive" }));
      } catch {
        // The close handler will schedule a reconnect if the socket is gone.
      }
    }, DEEPGRAM_KEEPALIVE_MS);
  }, [clearTranscriptionKeepAlive]);

  const clearTranscriptionReconnect = useCallback(() => {
    if (typeof window === "undefined" || transcriptionReconnectTimerRef.current === null) return;
    window.clearTimeout(transcriptionReconnectTimerRef.current);
    transcriptionReconnectTimerRef.current = null;
  }, []);

  const closeTranscriptionSocket = useCallback(() => {
    manualTranscriptionCloseRef.current = true;
    clearTranscriptionKeepAlive();
    clearTranscriptionReconnect();
    deepgramReconnectAttemptsRef.current = 0;
    stopMediaRecorder();
    stopBrowserRecognition(true);
    const socket = transcriptSocketRef.current;
    transcriptSocketRef.current = null;
    setTranscriptionConnected(false);
    setIsListening(false);
    setPartialTranscript("");
    onPartialTranscriptRef.current?.("");
    if (!socket || typeof WebSocket === "undefined") return;
    try {
      if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "close" }));
    } catch {
      // Closing a socket should not block media cleanup.
    }
    if (socket.readyState !== WebSocket.CLOSED) socket.close(1000);
  }, [clearTranscriptionKeepAlive, clearTranscriptionReconnect, stopBrowserRecognition, stopMediaRecorder]);

  const startBrowserFallback = useCallback(() => {
    if (!canCapture || transcriptionModeRef.current !== "browser-fallback") return;
    const SpeechRecognitionCtor = getSpeechRecognitionCtor();
    if (!SpeechRecognitionCtor) {
      setTranscriptionMode("unavailable");
      setSpeechError("Speech recognition is unavailable in this browser. Use Chrome or Edge, or configure Deepgram.");
      setIsListening(false);
      setSpeechStatus("Transcription unavailable");
      return;
    }

    stopBrowserRecognition(true);
    try {
      const recognition = new SpeechRecognitionCtor() as SpeechRecognitionLike;
      browserRecognitionRef.current = recognition;
      recognition.lang = language;
      recognition.continuous = true;
      recognition.interimResults = true;
      recognition.maxAlternatives = 3;
      recognition.onstart = () => {
        setIsListening(true);
        setSpeechStatus(captureModeRef.current === "consent" ? "Listening for yes or no" : "Listening to your answer");
      };
      recognition.onaudiostart = () => setIsListening(true);
      recognition.onspeechstart = () => {
        setSpeechStatus("Speech detected");
        setUserSpeaking(true);
      };
      recognition.onspeechend = () => {
        setSpeechStatus("Processing speech");
        setUserSpeaking(false);
      };
      recognition.onnomatch = () => {
        setSpeechError("");
        setSpeechStatus("Still listening");
      };
      recognition.onerror = (event: any) => {
        const error = String(event?.error || "speech error");
        const transient = error === "aborted" || error === "no-speech" || error === "network";
        if (error === "no-speech") {
          setSpeechError("");
          setSpeechStatus("Still listening");
        } else if (error === "network") {
          setSpeechError("");
          setSpeechStatus("Speech recognition reconnecting");
        } else if (!transient) {
          setSpeechError(`Speech recognition stopped: ${error}.`);
        }
        if (error === "audio-capture") {
          emitMediaEvent("mic_unavailable", { source: "browser_fallback", error });
        }
        setIsListening(false);
      };
      recognition.onresult = (event: any) => {
        for (let index = event.resultIndex; index < event.results.length; index += 1) {
          const result = event.results[index];
          const alternative = result[0];
          const text = String(alternative?.transcript || "").trim();
          if (!text) continue;
          if (result.isFinal) {
            setPartialTranscript("");
            onPartialTranscriptRef.current?.("");
            void onFinalTranscriptRef.current(text, alternative?.confidence || 0.7);
          } else {
            setPartialTranscript(text);
            onPartialTranscriptRef.current?.(text);
          }
        }
      };
      recognition.onend = () => {
        setIsListening(false);
        if (browserRecognitionRef.current === recognition) browserRecognitionRef.current = null;
        if (canCaptureRef.current && transcriptionModeRef.current === "browser-fallback" && callActiveRef.current && !botSpeakingRef.current) {
          window.setTimeout(() => startBrowserFallbackRef.current(), 350);
        }
      };
      recognition.start();
    } catch {
      setSpeechError("Could not start browser speech recognition.");
      setIsListening(false);
    }
  }, [canCapture, emitMediaEvent, language, setTranscriptionMode, stopBrowserRecognition]);

  useEffect(() => {
    startBrowserFallbackRef.current = startBrowserFallback;
  }, [startBrowserFallback]);

  const startMediaRecorder = useCallback(() => {
    stopMediaRecorder();
    if (!canCapture || transcriptionModeRef.current !== "deepgram") return;
    const socket = transcriptSocketRef.current;
    const stream = activeStreamRef.current;
    const track = stream?.getAudioTracks()[0];
    if (!socket || socket.readyState !== WebSocket.OPEN || !track || !isTrackUsable(track)) return;
    if (typeof MediaRecorder === "undefined") {
      if (hasBrowserSpeechFallback()) {
        setTranscriptionMode("browser-fallback");
        setSpeechError("");
        setSpeechStatus("Using browser speech fallback");
      } else {
        setSpeechError("This browser cannot encode realtime microphone audio.");
      }
      return;
    }
    try {
      const mimeType = getAudioMimeType();
      const recorder = new MediaRecorder(new MediaStream([track]), mimeType ? { mimeType } : undefined);
      recorder.ondataavailable = (event) => {
        if (!event.data.size || transcriptSocketRef.current?.readyState !== WebSocket.OPEN || !canCaptureRef.current) return;
        event.data.arrayBuffer().then((buffer) => {
          if (transcriptSocketRef.current?.readyState === WebSocket.OPEN && canCaptureRef.current) {
            transcriptSocketRef.current.send(buffer);
          }
        });
      };
      recorder.onerror = () => {
        if (hasBrowserSpeechFallback()) {
          setTranscriptionMode("browser-fallback");
          setSpeechError("");
          setSpeechStatus("Using browser speech fallback");
        } else {
          setSpeechError("Realtime audio encoder stopped unexpectedly.");
        }
        emitMediaEvent("transcription_error", { source: "media_recorder" });
      };
      recorder.start(300);
      mediaRecorderRef.current = recorder;
      setIsListening(true);
      setSpeechStatus(captureModeRef.current === "consent" ? "Listening for yes or no" : "Listening to your answer");
    } catch (error) {
      if (hasBrowserSpeechFallback()) {
        setTranscriptionMode("browser-fallback");
        setSpeechError("");
        setSpeechStatus("Using browser speech fallback");
      } else {
        setSpeechError(error instanceof Error ? error.message : "Could not start realtime audio capture.");
      }
    }
  }, [canCapture, emitMediaEvent, setTranscriptionMode, stopMediaRecorder]);

  const useBrowserTranscriptionFallback = useCallback(
    (status: string, unavailableError = "Realtime transcription failed and browser fallback is unavailable.") => {
      clearTranscriptionKeepAlive();
      clearTranscriptionReconnect();
      stopMediaRecorder();
      setTranscriptionConnected(false);
      if (hasBrowserSpeechFallback()) {
        setTranscriptionMode("browser-fallback");
        setSpeechError("");
        setSpeechStatus(status);
      } else {
        setTranscriptionMode("unavailable");
        setSpeechError(unavailableError);
        setSpeechStatus("Transcription unavailable");
      }
    },
    [clearTranscriptionKeepAlive, clearTranscriptionReconnect, setTranscriptionMode, stopMediaRecorder]
  );

  const scheduleDeepgramReconnect = useCallback(
    (reason: string) => {
      clearTranscriptionKeepAlive();
      stopMediaRecorder();
      setTranscriptionConnected(false);
      setIsListening(false);

      const socket = transcriptSocketRef.current;
      transcriptSocketRef.current = null;
      if (socket && typeof WebSocket !== "undefined" && socket.readyState !== WebSocket.CLOSED) {
        try {
          socket.close();
        } catch {
          // Closing a failing socket should not prevent reconnect scheduling.
        }
      }

      if (!callActiveRef.current || manualTranscriptionCloseRef.current || !interviewId || !micEnabledRef.current) return;
      if (transcriptionReconnectTimerRef.current !== null) return;

      const nextAttempt = deepgramReconnectAttemptsRef.current + 1;
      deepgramReconnectAttemptsRef.current = nextAttempt;
      if (nextAttempt > DEEPGRAM_MAX_RECONNECT_ATTEMPTS) {
        useBrowserTranscriptionFallback(
          "Emergency browser speech fallback",
          "Deepgram realtime transcription could not reconnect and browser speech fallback is not supported."
        );
        emitMediaEvent("transcription_error", {
          source: "deepgram_reconnect_exhausted",
          reason,
          attempts: nextAttempt - 1,
        });
        return;
      }

      const delay = Math.min(6000, DEEPGRAM_RECONNECT_BASE_MS * 2 ** (nextAttempt - 1));
      setSpeechError("");
      setSpeechStatus(`Deepgram reconnecting (${nextAttempt}/${DEEPGRAM_MAX_RECONNECT_ATTEMPTS})`);
      emitMediaEvent("transcription_error", {
        source: "deepgram_reconnect",
        reason,
        attempt: nextAttempt,
      });
      transcriptionReconnectTimerRef.current = window.setTimeout(() => {
        transcriptionReconnectTimerRef.current = null;
        connectTranscriptionRef.current();
      }, delay);
    },
    [
      clearTranscriptionKeepAlive,
      emitMediaEvent,
      interviewId,
      passiveSpeechStatus,
      stopMediaRecorder,
      useBrowserTranscriptionFallback,
    ]
  );

  const connectTranscription = useCallback(() => {
    if (!interviewId || typeof WebSocket === "undefined" || transcriptSocketRef.current) return;
    try {
      manualTranscriptionCloseRef.current = false;
      const socket = new WebSocket(transcriptSocketUrl(interviewId, round));
      transcriptSocketRef.current = socket;
      socket.binaryType = "arraybuffer";
      socket.onopen = () => {
        setSpeechError("");
        setSpeechStatus(canCaptureRef.current ? "Realtime transcription connecting" : passiveSpeechStatus());
      };
      socket.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data) as TranscriptionMessage;
          const eventName = payload.event || "";
          if (eventName === "transcription_connected") {
            deepgramReconnectAttemptsRef.current = 0;
            setTranscriptionMode("deepgram");
            setTranscriptionConnected(true);
            setSpeechStatus(canCaptureRef.current ? "Deepgram realtime transcription ready" : passiveSpeechStatus());
            startTranscriptionKeepAlive();
            emitMediaEvent("transcription_connected", {
              provider: payload.provider,
              model: payload.model,
              language: payload.language,
            });
            if (canCaptureRef.current) startMediaRecorder();
            return;
          }
          if (eventName === "transcription_unavailable") {
            clearTranscriptionKeepAlive();
            useBrowserTranscriptionFallback("Using browser speech fallback", "Deepgram is unavailable and browser speech fallback is not supported.");
            emitMediaEvent("transcription_unavailable", { reason: payload.reason });
            return;
          }
          if (eventName === "transcription_error") {
            scheduleDeepgramReconnect(String(payload.error || "deepgram_error"));
            emitMediaEvent("transcription_error", { error: payload.error });
            return;
          }
          if (eventName === "speech_started") {
            setUserSpeaking(true);
            setSpeechStatus("Speech detected");
            return;
          }
          if (eventName === "utterance_end") {
            setUserSpeaking(false);
            setSpeechStatus("Processing speech");
            return;
          }
          if (eventName === "transcript_partial") {
            const text = String(payload.text || "");
            setPartialTranscript(text);
            onPartialTranscriptRef.current?.(text);
            return;
          }
          if (eventName === "transcript_final") {
            const text = String(payload.text || "").trim();
            setPartialTranscript("");
            onPartialTranscriptRef.current?.("");
            if (text) {
              void onFinalTranscriptRef.current(text, payload.confidence || 0.72);
            }
          }
        } catch {
          // Ignore malformed transcription service frames.
        }
      };
      socket.onclose = () => {
        if (transcriptSocketRef.current === socket) transcriptSocketRef.current = null;
        clearTranscriptionKeepAlive();
        setTranscriptionConnected(false);
        stopMediaRecorder();
        if (
          callActiveRef.current &&
          micEnabledRef.current &&
          !manualTranscriptionCloseRef.current &&
          transcriptionModeRef.current !== "browser-fallback"
        ) {
          scheduleDeepgramReconnect("websocket_closed");
        }
      };
      socket.onerror = () => {
        if (micEnabledRef.current) {
          scheduleDeepgramReconnect("websocket_error");
        }
        emitMediaEvent("transcription_error", { source: "websocket" });
      };
    } catch {
      scheduleDeepgramReconnect("websocket_connect_failed");
    }
  }, [
    clearTranscriptionKeepAlive,
    emitMediaEvent,
    interviewId,
    round,
    passiveSpeechStatus,
    scheduleDeepgramReconnect,
    setTranscriptionMode,
    startMediaRecorder,
    startTranscriptionKeepAlive,
    stopMediaRecorder,
    useBrowserTranscriptionFallback,
  ]);

  useEffect(() => {
    connectTranscriptionRef.current = connectTranscription;
  }, [connectTranscription]);

  useEffect(() => {
    if (!callActive) {
      closeTranscriptionSocket();
      return;
    }
    if (transcriptionMode === "browser-fallback") {
      if (!canCapture) {
        stopMediaRecorder();
        stopBrowserRecognition(true);
        setIsListening(false);
        if (botSpeaking) {
          setSpeechStatus("Bot speaking");
        } else if (!micEnabled) {
          setSpeechStatus("Mic muted");
        } else if (captureMode === "idle") {
          setSpeechStatus("Mic is idle");
        }
        return;
      }
      startBrowserFallback();
      return;
    }
    if (!canCapture) {
      stopMediaRecorder();
      stopBrowserRecognition(true);
      setIsListening(false);
      if (botSpeaking) {
        setSpeechStatus("Bot speaking");
      } else if (!micEnabled) {
        setSpeechStatus("Mic muted");
        closeTranscriptionSocket();
      } else if (captureMode === "idle") {
        setSpeechStatus("Mic is idle");
      }
      if (micEnabled && (transcriptionMode === "deepgram" || transcriptionMode === "unavailable") && !transcriptSocketRef.current) {
        connectTranscription();
      }
      return;
    }
    if (transcriptionMode === "deepgram") {
      if (!transcriptSocketRef.current) {
        connectTranscription();
        return;
      }
      if (transcriptionConnected) startMediaRecorder();
    } else if (transcriptionMode === "unavailable") {
      connectTranscription();
    }
  }, [
    botSpeaking,
    callActive,
    canCapture,
    captureMode,
    closeTranscriptionSocket,
    connectTranscription,
    micEnabled,
    startBrowserFallback,
    startMediaRecorder,
    stopBrowserRecognition,
    stopMediaRecorder,
    transcriptionConnected,
    transcriptionMode,
  ]);

  const disconnectLiveKit = useCallback(async () => {
    const room = liveKitRoomRef.current;
    liveKitRoomRef.current = null;
    liveKitPublicationRef.current = null;
    liveKitMicCloneRef.current?.stop();
    liveKitMicCloneRef.current = null;
    setLiveKitConnected(false);
    setLiveKitState(ConnectionState.Disconnected);
    if (!room) return;
    try {
      await room.disconnect(false);
    } catch {
      // Room may already be disconnected.
    }
  }, []);

  const publishLiveKitMicrophone = useCallback(
    async (room: Room, audioTrack: MediaStreamTrack) => {
      liveKitMicCloneRef.current?.stop();
      liveKitMicCloneRef.current = null;
      liveKitPublicationRef.current = null;

      const clonedTrack = audioTrack.clone();
      liveKitMicCloneRef.current = clonedTrack;
      try {
        liveKitPublicationRef.current = await room.localParticipant.publishTrack(clonedTrack, {
          source: Track.Source.Microphone,
          name: "candidate-microphone",
          dtx: true,
          red: true,
        });
      } catch (error) {
        clonedTrack.stop();
        if (liveKitMicCloneRef.current === clonedTrack) liveKitMicCloneRef.current = null;
        liveKitPublicationRef.current = null;
        setLiveKitReason("");
        emitMediaEvent("livekit_error", {
          optional: true,
          source: "microphone_publish",
          error: error instanceof Error ? error.message : "LiveKit microphone publishing failed.",
        });
      }
    },
    [emitMediaEvent]
  );

  const connectLiveKit = useCallback(
    async (stream: MediaStream) => {
      if (!interviewId) return;
      try {
        const tokenResponse = await apiService.request<LiveKitTokenResponse>(
          `/api/realtime/interviews/${interviewId}/rounds/${round}/livekit-token`
        );
        if (!tokenResponse.enabled || !tokenResponse.serverUrl || !tokenResponse.token) {
          setLiveKitEnabled(false);
          setLiveKitReason(tokenResponse.reason || "LiveKit is not configured.");
          return;
        }

        const room = new Room({
          adaptiveStream: false,
          dynacast: false,
          publishDefaults: {
            dtx: true,
            red: true,
            stopMicTrackOnMute: false,
          },
        });
        liveKitRoomRef.current = room;
        setLiveKitRoom(room);
        setLiveKitEnabled(true);
        setLiveKitToken(tokenResponse.token);
        setLiveKitServerUrl(tokenResponse.serverUrl);
        setLiveKitReason("");

        room.on(RoomEvent.ConnectionStateChanged, (state) => setLiveKitState(state));
        room.on(RoomEvent.Reconnecting, () => setLiveKitState(ConnectionState.Reconnecting));
        room.on(RoomEvent.Reconnected, () => {
          setLiveKitState(ConnectionState.Connected);
          emitMediaEvent("livekit_connected", { reconnect: true });
        });
        room.on(RoomEvent.Disconnected, () => {
          setLiveKitConnected(false);
          setLiveKitState(ConnectionState.Disconnected);
          emitMediaEvent("livekit_disconnected");
        });
        await room.connect(tokenResponse.serverUrl, tokenResponse.token, { autoSubscribe: true });
        setLiveKitConnected(true);
        setLiveKitState(ConnectionState.Connected);
        emitMediaEvent("livekit_connected", { room: tokenResponse.room, identity: tokenResponse.identity });

        const audioTrack = stream.getAudioTracks()[0];
        if (audioTrack && micEnabledRef.current && audioTrack.readyState === "live") {
          await publishLiveKitMicrophone(room, audioTrack);
        }
      } catch (error) {
        setLiveKitEnabled(false);
        setLiveKitConnected(false);
        setLiveKitReason("");
        emitMediaEvent("livekit_error", { error: error instanceof Error ? error.message : "LiveKit connection failed." });
      }
    },
    [emitMediaEvent, interviewId, publishLiveKitMicrophone, round]
  );

  const attachActiveTrackListeners = useCallback(
    (stream: MediaStream) => {
      const handleEnded = (event: Event) => {
        const track = event.currentTarget as MediaStreamTrack | null;
        if (track?.kind === "audio") {
          setMicDeviceReady(false);
          micSignalPausedRef.current = false;
          setMicSignalPaused(false);
          stopMediaRecorder();
          stopBrowserRecognition(true);
          if (callActiveRef.current && micEnabledRef.current) {
            setSpeechError("");
            setSpeechStatus("Microphone reconnecting");
            emitMediaEvent("mic_stopped", { source: "track_ended", autoReconnect: true });
            if (!micRecoveryInFlightRef.current) {
              micRecoveryInFlightRef.current = true;
              if (micRecoveryTimerRef.current) window.clearTimeout(micRecoveryTimerRef.current);
              micRecoveryTimerRef.current = window.setTimeout(() => {
                micRecoveryTimerRef.current = null;
                void enableMicRef.current(true).finally(() => {
                  micRecoveryInFlightRef.current = false;
                });
              }, 300);
            }
            return;
          }
          setMicEnabledState(false);
          micEnabledRef.current = false;
          setSpeechError("The microphone stream disconnected. Reconnect before answering.");
          emitMediaEvent("mic_stopped", { source: "track_ended" });
        } else if (track?.kind === "video") {
          setCameraEnabledState(false);
          cameraEnabledRef.current = false;
          setCameraDeviceReady(false);
          emitMediaEvent("camera_stopped", { source: "track_ended" });
        }
      };
      const handleMute = (event: Event) => {
        const track = event.currentTarget as MediaStreamTrack | null;
        if (track?.kind === "audio") {
          if (signalPauseTimerRef.current) window.clearTimeout(signalPauseTimerRef.current);
          signalPauseTimerRef.current = window.setTimeout(() => {
            if (!track || !micEnabledRef.current || track.readyState !== "live" || !track.muted) return;
            micSignalPausedRef.current = true;
            setMicSignalPaused(true);
            setSpeechStatus("Mic signal paused; still listening");
            setSpeechError("");
            emitMediaEvent("mic_signal_paused", { source: "track_mute" });
          }, MICROPHONE_SIGNAL_PAUSE_GRACE_MS);
        } else if (track?.kind === "video") {
          setCameraDeviceReady(false);
          emitMediaEvent("camera_muted", { source: "track_mute" });
        }
      };
      const handleUnmute = (event: Event) => {
        const track = event.currentTarget as MediaStreamTrack | null;
        if (track?.kind === "audio") {
          if (signalPauseTimerRef.current) window.clearTimeout(signalPauseTimerRef.current);
          signalPauseTimerRef.current = null;
          micSignalPausedRef.current = false;
          setMicSignalPaused(false);
          updateTrackReadiness(stream);
          setSpeechError("");
          setSpeechStatus("Mic signal restored");
          emitMediaEvent("mic_signal_resumed", { source: "track_unmute" });
        } else if (track?.kind === "video") {
          updateTrackReadiness(stream);
          emitMediaEvent("camera_unmuted", { source: "track_unmute" });
        }
      };

      stream.getTracks().forEach((track) => {
        track.addEventListener("ended", handleEnded);
        track.addEventListener("mute", handleMute);
        track.addEventListener("unmute", handleUnmute);
      });

      return () => {
        stream.getTracks().forEach((track) => {
          track.removeEventListener("ended", handleEnded);
          track.removeEventListener("mute", handleMute);
          track.removeEventListener("unmute", handleUnmute);
        });
        if (signalPauseTimerRef.current) window.clearTimeout(signalPauseTimerRef.current);
        signalPauseTimerRef.current = null;
      };
    },
    [emitMediaEvent, stopBrowserRecognition, stopMediaRecorder, updateTrackReadiness]
  );

  const activeListenersCleanupRef = useRef<(() => void) | null>(null);

  const stopPreview = useCallback(() => {
    const stream = previewStreamRef.current;
    previewStreamRef.current = null;
    setPreviewStream(null);
    stopStream(stream);
    if (!activeStreamRef.current) {
      stopAudioMeter();
      setMicDeviceReady(false);
      setCameraDeviceReady(false);
    }
  }, [stopAudioMeter]);

  const stopCallMedia = useCallback(async () => {
    closeTranscriptionSocket();
    await disconnectLiveKit();
    activeListenersCleanupRef.current?.();
    activeListenersCleanupRef.current = null;
    if (micRecoveryTimerRef.current) window.clearTimeout(micRecoveryTimerRef.current);
    micRecoveryTimerRef.current = null;
    micRecoveryInFlightRef.current = false;
    stopAudioMeter();
    stopStream(activeStreamRef.current);
    activeStreamRef.current = null;
    setActiveStream(null);
    setMicDeviceReady(false);
    setCameraDeviceReady(false);
    micSignalPausedRef.current = false;
    setMicSignalPaused(false);
    setIsListening(false);
    setSpeechStatus("Mic is idle");
    setPartialTranscript("");
    onPartialTranscriptRef.current?.("");
  }, [closeTranscriptionSocket, disconnectLiveKit, stopAudioMeter]);

  useEffect(() => {
    if (!previewActive || callActive) {
      stopPreview();
      return;
    }
    let cancelled = false;
    async function startPreview() {
      if (!cameraEnabled && !micEnabled) {
        stopPreview();
        setMediaError("");
        return;
      }
      try {
        stopPreview();
        const stream = await requestUserMedia({
          camera: cameraEnabled,
          microphone: micEnabled,
          cameraDeviceId: selectedVideoDeviceIdRef.current,
          microphoneDeviceId: selectedAudioDeviceIdRef.current,
        });
        if (cancelled) {
          stopStream(stream);
          return;
        }
        previewStreamRef.current = stream;
        setPreviewStream(stream);
        micSignalPausedRef.current = false;
        setMicSignalPaused(false);
        updateTrackReadiness(stream);
        startAudioMeter(stream);
        setMediaError("");
        void refreshDevices();
      } catch (error) {
        if (cancelled) return;
        setMediaError(error instanceof Error ? error.message : "Unable to open camera or microphone preview.");
        setPreviewStream(null);
        previewStreamRef.current = null;
        updateTrackReadiness(null);
      }
    }
    void startPreview();
    return () => {
      cancelled = true;
    };
  }, [
    callActive,
    cameraEnabled,
    micEnabled,
    previewActive,
    refreshDevices,
    selectedAudioDeviceId,
    selectedVideoDeviceId,
    startAudioMeter,
    stopPreview,
    updateTrackReadiness,
  ]);

  const startCallMedia = useCallback(async () => {
    setMediaError("");
    setSpeechError("");
    const previewStream = previewStreamRef.current;
    const previewUsable = Boolean(
      previewStream &&
        (!cameraEnabledRef.current || isTrackUsable(previewStream.getVideoTracks()[0])) &&
        (!micEnabledRef.current || isTrackUsable(previewStream.getAudioTracks()[0]))
    );
    const stream =
      previewUsable && previewStream
        ? previewStream
        : await requestUserMedia({
            camera: cameraEnabledRef.current,
            microphone: micEnabledRef.current,
            cameraDeviceId: selectedVideoDeviceIdRef.current,
            microphoneDeviceId: selectedAudioDeviceIdRef.current,
          });

    if (previewStream && previewStream !== stream) stopStream(previewStream);
    previewStreamRef.current = null;
    setPreviewStream(null);
    activeStreamRef.current = stream;
    setActiveStream(stream);
    micSignalPausedRef.current = false;
    setMicSignalPaused(false);
    updateTrackReadiness(stream);
    startAudioMeter(stream);
    activeListenersCleanupRef.current?.();
    activeListenersCleanupRef.current = attachActiveTrackListeners(stream);
    await connectLiveKit(stream);
    emitMediaEvent("media_state", {
      source: "call_started",
      cameraEnabled: cameraEnabledRef.current,
      micEnabled: micEnabledRef.current,
      micTrackLive: isTrackUsable(stream.getAudioTracks()[0]),
      cameraTrackLive: isTrackUsable(stream.getVideoTracks()[0]),
    });
    return stream;
  }, [
    attachActiveTrackListeners,
    connectLiveKit,
    emitMediaEvent,
    selectedAudioDeviceId,
    selectedVideoDeviceId,
    startAudioMeter,
    updateTrackReadiness,
  ]);

  const setMicEnabled = useCallback(
    async (enabled: boolean) => {
      setMicEnabledState(enabled);
      micEnabledRef.current = enabled;
      const stream = activeStreamRef.current || previewStreamRef.current;
      if (!stream) return;
      if (!enabled) {
        stream.getAudioTracks().forEach((track) => {
          track.enabled = false;
        });
        if (liveKitMicCloneRef.current) liveKitMicCloneRef.current.enabled = false;
        await liveKitPublicationRef.current?.mute().catch(() => undefined);
        stopMediaRecorder();
        stopBrowserRecognition(true);
        setIsListening(false);
        setSpeechStatus("Mic muted");
        setAudioLevel(0);
        setUserSpeaking(false);
        emitMediaEvent("mic_muted", { source: "call_control" });
        updateTrackReadiness(stream);
        return;
      }

      try {
        let track = stream.getAudioTracks()[0];
        if (!track || track.readyState !== "live") {
          const audioStream = await requestUserMedia({
            camera: false,
            microphone: true,
            microphoneDeviceId: selectedAudioDeviceIdRef.current,
          });
          activeListenersCleanupRef.current?.();
          activeListenersCleanupRef.current = null;
          removeExistingTracks(stream, "audio");
          track = audioStream.getAudioTracks()[0];
          if (track) stream.addTrack(track);
          activeListenersCleanupRef.current = activeStreamRef.current ? attachActiveTrackListeners(activeStreamRef.current) : null;
          if (liveKitRoomRef.current && track) {
            await publishLiveKitMicrophone(liveKitRoomRef.current, track);
          }
        }
        if (track) track.enabled = true;
        if (liveKitMicCloneRef.current) liveKitMicCloneRef.current.enabled = true;
        micSignalPausedRef.current = false;
        setMicSignalPaused(false);
        await liveKitPublicationRef.current?.unmute().catch(() => undefined);
        startAudioMeter(stream);
        const { micReady } = updateTrackReadiness(stream);
        setSpeechError("");
        if (micReady) {
          setSpeechStatus(botSpeakingRef.current ? "Bot speaking" : captureModeRef.current === "idle" ? "Mic is idle" : "Mic ready");
        }
        emitMediaEvent("mic_unmuted", { source: "call_control" });
      } catch (error) {
        setMicEnabledState(false);
        micEnabledRef.current = false;
        setMicDeviceReady(false);
        setSpeechError(error instanceof Error ? error.message : "Could not turn the microphone on.");
        emitMediaEvent("mic_unavailable", { source: "call_control" });
      }
    },
    [
      attachActiveTrackListeners,
      emitMediaEvent,
      publishLiveKitMicrophone,
      startAudioMeter,
      stopBrowserRecognition,
      stopMediaRecorder,
      updateTrackReadiness,
    ]
  );

  const setCameraEnabled = useCallback(
    async (enabled: boolean) => {
      setCameraEnabledState(enabled);
      cameraEnabledRef.current = enabled;
      const stream = activeStreamRef.current || previewStreamRef.current;
      if (!stream) return;
      if (!enabled) {
        stream.getVideoTracks().forEach((track) => {
          track.enabled = false;
        });
        setCameraDeviceReady(false);
        emitMediaEvent("camera_off", { source: "call_control" });
        return;
      }

      try {
        let track = stream.getVideoTracks()[0];
        if (!track || track.readyState !== "live") {
          const videoStream = await requestUserMedia({
            camera: true,
            microphone: false,
            cameraDeviceId: selectedVideoDeviceIdRef.current,
          });
          removeExistingTracks(stream, "video");
          track = videoStream.getVideoTracks()[0];
          if (track) stream.addTrack(track);
          activeListenersCleanupRef.current?.();
          activeListenersCleanupRef.current = activeStreamRef.current ? attachActiveTrackListeners(activeStreamRef.current) : null;
        }
        if (track) track.enabled = true;
        updateTrackReadiness(stream);
        emitMediaEvent("camera_on", { source: "call_control" });
      } catch (error) {
        setCameraEnabledState(false);
        cameraEnabledRef.current = false;
        setMediaError(error instanceof Error ? error.message : "Could not turn the camera on.");
        emitMediaEvent("camera_unavailable", { source: "call_control" });
      }
    },
    [attachActiveTrackListeners, emitMediaEvent, updateTrackReadiness]
  );

  useEffect(() => {
    enableMicRef.current = setMicEnabled;
  }, [setMicEnabled]);

  const selectAudioInput = useCallback(
    async (deviceId: string) => {
      const nextDeviceId = deviceId || null;
      selectedAudioDeviceIdRef.current = nextDeviceId;
      setSelectedAudioDeviceId(nextDeviceId);
      if (micEnabledRef.current && (activeStreamRef.current || previewStreamRef.current)) {
        await setMicEnabled(true);
      }
    },
    [setMicEnabled]
  );

  const selectVideoInput = useCallback(
    async (deviceId: string) => {
      const nextDeviceId = deviceId || null;
      selectedVideoDeviceIdRef.current = nextDeviceId;
      setSelectedVideoDeviceId(nextDeviceId);
      if (cameraEnabledRef.current && (activeStreamRef.current || previewStreamRef.current)) {
        await setCameraEnabled(true);
      }
    },
    [setCameraEnabled]
  );

  useEffect(() => {
    return () => {
      void stopCallMedia();
      stopPreview();
    };
  }, [stopCallMedia, stopPreview]);

  return {
    previewStream,
    activeStream,
    startCallMedia,
    stopCallMedia,
    stopPreview,
    cameraEnabled,
    micEnabled,
    setCameraEnabled,
    setMicEnabled,
    cameraDeviceReady,
    micDeviceReady,
    micSignalPaused,
    audioLevel,
    userSpeaking,
    mediaError,
    speechError,
    speechStatus,
    isListening,
    partialTranscript,
    setPartialTranscript,
    audioInputs,
    videoInputs,
    selectedAudioDeviceId,
    selectedVideoDeviceId,
    selectAudioInput,
    selectVideoInput,
    liveKitRoom,
    liveKitToken,
    liveKitServerUrl,
    liveKitEnabled,
    liveKitConnected,
    liveKitState,
    liveKitReason,
    transcriptionMode,
    transcriptionConnected,
    realtimeReady: liveKitConnected || transcriptionConnected || transcriptionMode === "browser-fallback",
    refreshDevices,
  };
}
