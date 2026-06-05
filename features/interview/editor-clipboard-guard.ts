"use client";

type ClipboardLikeEvent = {
  preventDefault: () => void;
  stopPropagation: () => void;
};

function blockEvent(event: ClipboardLikeEvent, onBlocked: () => void) {
  event.preventDefault();
  event.stopPropagation();
  onBlocked();
}

function isClipboardShortcut(event: KeyboardEvent) {
  const key = event.key.toLowerCase();
  return (
    ((event.ctrlKey || event.metaKey) && ["c", "x", "v"].includes(key)) ||
    (event.shiftKey && key === "insert")
  );
}

export function blockEditorClipboardEvent(event: ClipboardLikeEvent, onBlocked: () => void) {
  blockEvent(event, onBlocked);
}

export function installMonacoClipboardGuard(editor: any, onBlocked: () => void) {
  const disposables: Array<{ dispose: () => void }> = [];
  const domNode = editor?.getDomNode?.() as HTMLElement | null;
  const blockDomEvent = (event: Event) => blockEvent(event, onBlocked);

  disposables.push(
    editor.onKeyDown((event: any) => {
      const browserEvent = event.browserEvent as KeyboardEvent | undefined;
      if (!browserEvent || !isClipboardShortcut(browserEvent)) return;
      event.preventDefault();
      event.stopPropagation();
      browserEvent.preventDefault();
      browserEvent.stopPropagation();
      onBlocked();
    })
  );

  if (domNode) {
    ["copy", "cut", "paste", "drop", "contextmenu"].forEach((eventName) => {
      domNode.addEventListener(eventName, blockDomEvent, true);
    });
  }

  return () => {
    disposables.forEach((item) => item.dispose());
    if (domNode) {
      ["copy", "cut", "paste", "drop", "contextmenu"].forEach((eventName) => {
        domNode.removeEventListener(eventName, blockDomEvent, true);
      });
    }
  };
}
