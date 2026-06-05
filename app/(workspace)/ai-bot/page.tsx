"use client";

import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { useChatStore } from "@/stores/chat-store";
import { apiService } from "@/services/api-service";
import { ChevronDown, Send } from "lucide-react";
import Image from "next/image";
import dynamic from "next/dynamic";
import { useCallback, useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";

const Editor = dynamic(() => import("@monaco-editor/react"), {
  ssr: false,
  loading: () => <div className="h-32 bg-[#0b0f14]" />,
});

function editorLanguage(language?: string) {
  const normalized = (language || "plaintext").toLowerCase();
  const aliases: Record<string, string> = {
    js: "javascript",
    jsx: "javascript",
    py: "python",
    ts: "typescript",
    tsx: "typescript",
    shell: "shell",
    bash: "shell",
    sh: "shell",
    jsonc: "json",
  };
  return aliases[normalized] || normalized;
}

function InlineText({ text }: { text: string }) {
  const parts = text.split(/(`[^`]+`|\*\*[^*]+\*\*)/g);
  return (
    <>
      {parts.map((part, index) => {
        if (part.startsWith("**") && part.endsWith("**")) {
          return (
            <strong key={index} className="font-semibold text-ink">
              {part.slice(2, -2)}
            </strong>
          );
        }

        if (part.startsWith("`") && part.endsWith("`")) {
          return (
            <code key={index} className="rounded border border-hairline bg-surface-1 px-1.5 py-0.5 text-[0.9em] text-ink">
              {part.slice(1, -1)}
            </code>
          );
        }

        return (
          <span key={index}>{part}</span>
        );
      })}
    </>
  );
}

function TextBlock({ text }: { text: string }) {
  const normalizedText = text.includes("\\n") && !text.includes("\n") ? text.replace(/\\n/g, "\n") : text;
  const lines = normalizedText.split("\n");

  return (
    <div className="space-y-2 text-body leading-relaxed">
      {lines.map((line, index) => {
        const cleanLine = line.replace(/\\([*`_#-])/g, "$1").trimEnd();
        const headingMatch = cleanLine.match(/^\s*#{1,4}\s+(.*)$/);
        const bulletMatch = cleanLine.match(/^\s*[-*]\s+(.*)$/);
        const numberedMatch = cleanLine.match(/^\s*(\d+)[.)]\s+(.*)$/);

        if (!cleanLine.trim()) {
          return <div key={index} className="h-2" />;
        }

        if (headingMatch) {
          return (
            <h3 key={index} className="pt-1 text-body font-semibold text-ink">
              <InlineText text={headingMatch[1]} />
            </h3>
          );
        }

        if (bulletMatch) {
          return (
            <div key={index} className="flex gap-2">
              <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-accent-blue" />
              <p className="min-w-0">
                <InlineText text={bulletMatch[1]} />
              </p>
            </div>
          );
        }

        if (numberedMatch) {
          return (
            <div key={index} className="flex gap-2">
              <span className="min-w-5 text-ink-muted">{numberedMatch[1]}.</span>
              <p className="min-w-0">
                <InlineText text={numberedMatch[2]} />
              </p>
            </div>
          );
        }

        return (
          <p key={index}>
            <InlineText text={cleanLine} />
          </p>
        );
      })}
    </div>
  );
}

function MessageContent({ content }: { content: string }) {
  const parts: Array<{ type: "text" | "code"; value: string; language?: string }> = [];
  const regex = /```([\w.+-]*)\n?([\s\S]*?)```/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = regex.exec(content)) !== null) {
    if (match.index > lastIndex) {
      parts.push({ type: "text", value: content.slice(lastIndex, match.index) });
    }
    parts.push({ type: "code", language: match[1] || "code", value: match[2].trimEnd() });
    lastIndex = regex.lastIndex;
  }

  if (lastIndex < content.length) {
    parts.push({ type: "text", value: content.slice(lastIndex) });
  }

  if (parts.length === 0) {
    return <TextBlock text={content} />;
  }

  return (
    <div className="space-y-3">
      {parts.map((part, index) =>
        part.type === "code" ? (
          <div key={index} className="overflow-hidden rounded-lg border border-hairline bg-[#0b0f14]">
            <div className="flex h-9 items-center justify-between border-b border-hairline bg-black/40 px-3">
              <span className="text-micro uppercase text-ink-muted">
                {part.language}
              </span>
            </div>
            <Editor
              height={Math.min(448, Math.max(120, part.value.split("\n").length * 22 + 32))}
              language={editorLanguage(part.language)}
              theme="vs-dark"
              value={part.value}
              options={{
                readOnly: true,
                domReadOnly: true,
                minimap: { enabled: false },
                lineNumbers: "on",
                glyphMargin: false,
                folding: false,
                renderLineHighlight: "none",
                scrollBeyondLastLine: false,
                wordWrap: "on",
                wrappingIndent: "same",
                fontSize: 13,
                lineHeight: 22,
                tabSize: editorLanguage(part.language) === "python" ? 4 : 2,
                insertSpaces: true,
                detectIndentation: false,
                overviewRulerLanes: 0,
                hideCursorInOverviewRuler: true,
                scrollbar: {
                  vertical: "auto",
                  horizontal: "auto",
                  useShadows: false,
                },
                padding: { top: 12, bottom: 12 },
              }}
            />
          </div>
        ) : (
          <TextBlock key={index} text={part.value} />
        )
      )}
    </div>
  );
}

function TypingIndicator({ bare = false }: { bare?: boolean }) {
  return (
    <div className={cn("flex w-fit items-center gap-2", !bare && "rounded-2xl bg-surface-2 px-4 py-3")}>
      <div className="flex gap-1">
        <div className="w-2 h-2 bg-accent-blue rounded-full animate-bounce" style={{ animationDelay: "0ms" }} />
        <div className="w-2 h-2 bg-accent-blue rounded-full animate-bounce" style={{ animationDelay: "150ms" }} />
        <div className="w-2 h-2 bg-accent-blue rounded-full animate-bounce" style={{ animationDelay: "300ms" }} />
      </div>
    </div>
  );
}

function BotAvatar() {
  return (
    <div className="w-12 h-12 rounded-lg bg-black border border-hairline flex items-center justify-center flex-shrink-0 overflow-hidden shadow-2xl">
      <Image src="/logo.png" alt="Bot Avatar" width={36} height={36} className="object-contain" />
    </div>
  );
}

export default function AIBotPage() {
  const { messages, addMessage, clearMessages } = useChatStore();
  const [input, setInput] = useState("");
  const [typingMessage, setTypingMessage] = useState("");
  const [isTyping, setIsTyping] = useState(false);
  const [showScrollButton, setShowScrollButton] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const stickToBottomRef = useRef(true);

  const scrollToBottom = useCallback((behavior: ScrollBehavior = "smooth") => {
    messagesEndRef.current?.scrollIntoView({ behavior, block: "end" });
  }, []);

  const handleScroll = (e: React.UIEvent<HTMLDivElement>) => {
    const element = e.currentTarget;
    const isNearBottom = element.scrollHeight - element.scrollTop - element.clientHeight < 100;
    stickToBottomRef.current = isNearBottom;
    setShowScrollButton(!isNearBottom);
  };

  const typeMessage = (message: string) => {
    setIsTyping(true);
    setTypingMessage("");
    let index = 0;
    const chunkSize = message.length > 1200 ? 5 : message.length > 500 ? 3 : 2;
    
    const interval = setInterval(() => {
      if (index < message.length) {
        const nextChunk = message.slice(index, index + chunkSize);
        setTypingMessage((prev) => prev + nextChunk);
        index += chunkSize;
      } else {
        clearInterval(interval);
        setIsTyping(false);
        addMessage({
          role: "assistant",
          content: message,
        });
        setTypingMessage("");
      }
    }, 12);
  };

  const parseStreamEvent = (block: string) => {
    const lines = block.split(/\r?\n/);
    let event = "message";
    const dataLines: string[] = [];

    lines.forEach((line) => {
      if (line.startsWith("event:")) {
        event = line.slice(6).trim();
      }
      if (line.startsWith("data:")) {
        dataLines.push(line.slice(5).trimStart());
      }
    });

    if (dataLines.length === 0) return null;

    return {
      event,
      data: JSON.parse(dataLines.join("\n")),
    } as { event: string; data: any };
  };

  const requestBotResponse = async (message: string) => {
    const headers = new Headers({ "Content-Type": "application/json" });
    const token = apiService.getToken();
    if (token) {
      headers.set("Authorization", `Bearer ${token}`);
    }

    const response = await fetch(`${apiService.baseURL}/api/bot/message/stream`, {
      method: "POST",
      headers,
      body: JSON.stringify({ message }),
    });

    if (!response.ok) {
      let detail = response.statusText;
      try {
        const payload = await response.json();
        detail = payload.detail || detail;
      } catch {
        // Keep the HTTP status text if the backend did not return JSON.
      }
      throw new Error(detail);
    }

    if (!response.body) {
      throw new Error("The backend did not open a response stream.");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let finalResponse = "";

    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
      const blocks = buffer.split(/\n\n/);
      buffer = blocks.pop() || "";

      for (const block of blocks) {
        const parsed = parseStreamEvent(block.trim());
        if (!parsed) continue;

        if (parsed.event === "message") {
          finalResponse = parsed.data.response || "";
        }

        if (parsed.event === "error") {
          throw new Error(parsed.data.message || "The bot response failed.");
        }
      }

      if (done) break;
    }

    if (!finalResponse) {
      throw new Error("The bot did not return a response. Please try again.");
    }

    return finalResponse;
  };

  const handleSend = async () => {
    if (!input.trim()) return;

    const message = input;
    stickToBottomRef.current = true;
    addMessage({
      role: "user",
      content: message,
    });

    setInput("");

    try {
      setIsTyping(true);
      const response = await requestBotResponse(message);
      typeMessage(response);
    } catch (error) {
      typeMessage(error instanceof Error ? error.message : "I could not reach the backend.");
    }
  };

  useEffect(() => {
    if (stickToBottomRef.current) {
      scrollToBottom();
    }
  }, [messages, scrollToBottom, typingMessage]);

  useEffect(() => {
    apiService
      .request<Array<{ role: "user" | "assistant"; content: string }>>("/api/bot/history")
      .then((history) => {
        stickToBottomRef.current = true;
        clearMessages();
        history.forEach((message) => {
          addMessage({ role: message.role, content: message.content });
        });
        window.setTimeout(() => scrollToBottom("auto"), 0);
      })
      .catch(() => {
        // Chat can still start locally and send on the next backend attempt.
      });
  }, [addMessage, clearMessages, scrollToBottom]);

  const suggestedQuestions = [
    "How can I improve my DSA skills?",
    "What are my weak areas?",
    "Show me my progress",
    "Tips for technical interviews",
  ];

  return (
    
    <div className="flex h-[calc(100vh-4rem)] min-h-0 flex-col overflow-hidden">
      {/* Header */}
      <div className="mb-4 flex-shrink-0">
        <div className="flex items-center gap-3 mb-2">
          <BotAvatar />
          <div>
            <h1 className="text-display-md text-ink">AI Consultant</h1>
            <p className="text-body-sm text-ink-muted">
              Your personal interview preparation mentor
            </p>
          </div>
        </div>
      </div>

      {/* Chat Container */}
      <Card className="relative flex min-h-0 flex-1 flex-col overflow-hidden bg-surface-1 border-hairline">
        <CardContent className="flex min-h-0 flex-1 flex-col p-0">
          {/* Messages Area with Scroll */}
          <div 
            className="min-h-0 flex-1 overflow-y-scroll p-4 scroll-smooth md:p-6"
            onScroll={handleScroll}
            ref={scrollRef}
            style={{
              scrollbarWidth: 'thin',
              scrollbarColor: '#2b2b2b #141414',
            }}
          >
            {messages.length === 0 && !isTyping ? (
              <div className="flex min-h-full flex-col items-center justify-center text-center">
                <div className="w-32 h-32 rounded-xl bg-black border border-hairline flex items-center justify-center mb-6 overflow-hidden shadow-2xl">
                  <Image src="/logo.png" alt="Bot Avatar Large" width={96} height={96} className="object-contain" />
                </div>
                <h3 className="text-headline text-ink mb-2">Start a Conversation</h3>
                <p className="text-body text-ink-muted max-w-md mb-8">
                  Ask me anything about your interview performance, learning roadmap, or career guidance
                </p>
                
                {/* Suggested Questions */}
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 w-full max-w-2xl">
                  {suggestedQuestions.map((question, index) => (
                    <button
                      key={index}
                      onClick={() => setInput(question)}
                      className="p-4 bg-surface-2 border border-hairline rounded-lg text-body-sm text-ink-muted hover:text-ink hover:border-accent-blue/50 transition-all text-left"
                    >
                      {question}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <div className="space-y-6 pb-2">
                {messages.map((message) => (
                  <div
                    key={message.id}
                    className={cn(
                      "flex gap-3",
                      message.role === "user" ? "justify-end" : "justify-start"
                    )}
                  >
                    {message.role === "assistant" && <BotAvatar />}
                    
                    <div
                      className={cn(
                        "max-w-[min(80%,56rem)] break-words px-4 py-3 rounded-2xl",
                        message.role === "user"
                          ? "bg-accent-blue text-ink rounded-br-sm"
                          : "bg-surface-2 text-ink rounded-bl-sm"
                      )}
                    >
                      <MessageContent content={message.content} />
                    </div>
                  </div>
                ))}
                
                {/* Typing Animation */}
                {isTyping && (
                  <div className="flex gap-3 justify-start">
                    <BotAvatar />
                    {typingMessage ? (
                      <div className="max-w-[80%] px-4 py-3 rounded-2xl bg-surface-2 text-ink rounded-bl-sm">
                        <div className="relative">
                          <MessageContent content={typingMessage} />
                          <span className="inline-block w-1 h-4 bg-accent-blue ml-1 animate-pulse" />
                        </div>
                      </div>
                    ) : (
                      <TypingIndicator />
                    )}
                  </div>
                )}
                
                <div ref={messagesEndRef} />
              </div>
            )}
          </div>

          {/* Scroll to Bottom Button */}
          {showScrollButton && (
            <button
              onClick={() => {
                stickToBottomRef.current = true;
                scrollToBottom();
              }}
              className="absolute bottom-24 right-8 w-10 h-10 bg-surface-2 border border-hairline rounded-full flex items-center justify-center hover:bg-accent-blue transition-colors shadow-lg"
            >
              <ChevronDown className="w-5 h-5 text-ink" />
            </button>
          )}

          {/* Input Area */}
          <div className="flex-shrink-0 border-t border-hairline bg-surface-2/50 p-4">
            <div className="flex gap-3 max-w-4xl mx-auto">
              <Input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    handleSend();
                  }
                }}
                placeholder="Ask me anything..."
                className="bg-surface-1 border-hairline text-ink flex-1"
                disabled={isTyping}
              />
              <Button
                onClick={handleSend}
                disabled={!input.trim() || isTyping}
                className="bg-accent-blue text-ink hover:bg-accent-blue/90 rounded-lg px-6"
              >
                <Send className="w-4 h-4" />
              </Button>
            </div>
            <p className="text-micro text-ink-muted text-center mt-2">
              AI can make mistakes. Verify important information.
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  
  );
}
