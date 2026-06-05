import { create } from "zustand";
import type { ChatMessage, ChatState, ChatContext } from "@/types";

interface ChatStore extends ChatState {
  addMessage: (message: Omit<ChatMessage, "id" | "timestamp">) => void;
  setStreaming: (isStreaming: boolean) => void;
  setContext: (context: ChatContext | null) => void;
  clearMessages: () => void;
  updateLastMessage: (content: string) => void;
}

export const useChatStore = create<ChatStore>((set, get) => ({
  messages: [],
  isStreaming: false,
  context: null,

  addMessage: (message) =>
    set((state) => ({
      messages: [
        ...state.messages,
        {
          ...message,
          id: `msg-${Date.now()}-${Math.random()}`,
          timestamp: new Date(),
        },
      ],
    })),

  setStreaming: (isStreaming) => set({ isStreaming }),

  setContext: (context) => set({ context }),

  clearMessages: () => set({ messages: [] }),

  updateLastMessage: (content) =>
    set((state) => {
      const messages = [...state.messages];
      if (messages.length > 0) {
        messages[messages.length - 1] = {
          ...messages[messages.length - 1],
          content,
        };
      }
      return { messages };
    }),
}));
