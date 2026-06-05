"use client";

import { AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

interface InAppConfirmDialogProps {
  open: boolean;
  title: string;
  description: string;
  confirmLabel: string;
  cancelLabel?: string;
  variant?: "primary" | "danger";
  onOpenChange: (open: boolean) => void;
  onConfirm: () => void;
}

export function InAppConfirmDialog({
  open,
  title,
  description,
  confirmLabel,
  cancelLabel = "Cancel",
  variant = "primary",
  onOpenChange,
  onConfirm,
}: InAppConfirmDialogProps) {
  const confirmClass =
    variant === "danger"
      ? "bg-red-600 text-white hover:bg-red-500"
      : "bg-primary text-on-primary hover:bg-primary/90";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        showCloseButton={false}
        className="w-[min(460px,calc(100vw-2rem))] rounded-lg border border-hairline bg-surface-1 p-0 text-ink shadow-2xl"
      >
        <div className="space-y-4 p-5">
          <DialogHeader className="items-start gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-full border border-gradient-orange/40 bg-gradient-orange/10">
              <AlertTriangle className="h-5 w-5 text-gradient-orange" />
            </div>
            <div className="space-y-2 text-left">
              <DialogTitle className="text-headline text-ink">{title}</DialogTitle>
              <DialogDescription className="text-body-sm text-ink-muted">{description}</DialogDescription>
            </div>
          </DialogHeader>
        </div>
        <div className="flex flex-col-reverse gap-2 border-t border-hairline bg-surface-2 p-4 sm:flex-row sm:justify-end">
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)} className="border-hairline">
            {cancelLabel}
          </Button>
          <Button
            type="button"
            onClick={() => {
              onOpenChange(false);
              onConfirm();
            }}
            className={confirmClass}
          >
            {confirmLabel}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
