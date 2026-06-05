"use client";

import { LiveKitRoom, RoomAudioRenderer, StartAudio } from "@livekit/components-react";
import type { Room } from "livekit-client";

type InterviewLiveKitAudioLayerProps = {
  room: Room | null;
  serverUrl?: string;
  token?: string;
  connected: boolean;
};

export function InterviewLiveKitAudioLayer({
  room,
  serverUrl,
  token,
  connected,
}: InterviewLiveKitAudioLayerProps) {
  if (!room || !serverUrl || !token) return null;

  return (
    <LiveKitRoom
      room={room}
      serverUrl={serverUrl}
      token={token}
      connect={false}
      audio={false}
      video={false}
      className="pointer-events-none fixed bottom-28 left-1/2 z-[70] -translate-x-1/2"
    >
      <RoomAudioRenderer room={room} muted={!connected} />
      <StartAudio
        label="Enable interview audio"
        className="pointer-events-auto rounded-md border border-hairline bg-surface-1 px-4 py-2 text-body-sm text-ink shadow-2xl"
      />
    </LiveKitRoom>
  );
}
