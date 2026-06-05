"use client";

import { useCallback, useEffect, useState } from "react";
import { useRoadmapStore } from "@/stores/roadmap-store";
import { EmptyState } from "@/components/empty-state";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Progress } from "@/components/ui/progress";
import { Textarea } from "@/components/ui/textarea";
import { apiService } from "@/services/api-service";
import { CheckCircle2, Edit3, Loader2, Map, Target } from "lucide-react";
import type { Roadmap } from "@/types";
import { cleanGeneratedText } from "@/lib/generated-text";
import { cn } from "@/lib/utils";

type RevisionPreview = {
  summary: string;
  pros: string[];
  cons: string[];
  proposedRoadmap: Roadmap;
  provider?: string;
};

function formatDate(value: Date | string) {
  return new Date(value).toLocaleDateString("en", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function roadmapText(value: unknown, fallback = "") {
  return cleanGeneratedText(value, fallback);
}

export default function RoadmapsPage() {
  const { roadmaps, setRoadmaps, updateRoadmap, isLoading, setLoading } = useRoadmapStore();
  const [error, setError] = useState("");
  const [selectedRoadmapId, setSelectedRoadmapId] = useState<string | null>(null);
  const [updateOpen, setUpdateOpen] = useState(false);
  const [updateInstructions, setUpdateInstructions] = useState("");
  const [revisionPreview, setRevisionPreview] = useState<RevisionPreview | null>(null);
  const [isPreviewing, setIsPreviewing] = useState(false);
  const [isApplying, setIsApplying] = useState(false);
  const selectedRoadmap =
    roadmaps.find((roadmap) => roadmap.id === selectedRoadmapId) ||
    roadmaps.find((roadmap) => roadmap.isActive) ||
    roadmaps[0];

  const loadRoadmaps = useCallback(async () => {
    setError("");
    setLoading(true);
    try {
      const response = await apiService.request<Roadmap[]>("/api/roadmaps");
      setRoadmaps(response);
      setSelectedRoadmapId((current) => current || response.find((item) => item.isActive)?.id || response[0]?.id || null);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Unable to load roadmaps.");
    } finally {
      setLoading(false);
    }
  }, [setLoading, setRoadmaps]);

  useEffect(() => {
    loadRoadmaps();
  }, [loadRoadmaps]);

  const activateRoadmap = async (roadmapId: string) => {
    setError("");
    try {
      await apiService.request<Roadmap>(`/api/roadmaps/${roadmapId}/activate`, {
        method: "POST",
      });
      setSelectedRoadmapId(roadmapId);
      await loadRoadmaps();
    } catch (activateError) {
      setError(activateError instanceof Error ? activateError.message : "Unable to activate roadmap.");
    }
  };

  const toggleTask = async (roadmapId: string, milestoneId: string, taskId: string) => {
    try {
      const updated = await apiService.request<Roadmap>(
        `/api/roadmaps/${roadmapId}/milestones/${milestoneId}/tasks/${taskId}/toggle`,
        { method: "POST" }
      );
      updateRoadmap(roadmapId, updated);
    } catch (toggleError) {
      setError(toggleError instanceof Error ? toggleError.message : "Unable to update task.");
    }
  };

  const requestRevisionPreview = async () => {
    if (!selectedRoadmap || !updateInstructions.trim()) return;
    setError("");
    setIsPreviewing(true);
    setRevisionPreview(null);
    try {
      const preview = await apiService.request<RevisionPreview>(
        `/api/roadmaps/${selectedRoadmap.id}/revision-preview`,
        {
          method: "POST",
          body: { instructions: updateInstructions },
        }
      );
      setRevisionPreview(preview);
    } catch (previewError) {
      setError(previewError instanceof Error ? previewError.message : "Unable to preview roadmap update.");
    } finally {
      setIsPreviewing(false);
    }
  };

  const applyRevision = async () => {
    if (!selectedRoadmap || !revisionPreview) return;
    setIsApplying(true);
    try {
      const updated = await apiService.request<Roadmap>(
        `/api/roadmaps/${selectedRoadmap.id}/revision-apply`,
        {
          method: "POST",
          body: {
            proposed_roadmap: revisionPreview.proposedRoadmap,
            make_active: true,
          },
        }
      );
      updateRoadmap(updated.id, updated);
      setSelectedRoadmapId(updated.id);
      setUpdateOpen(false);
      setUpdateInstructions("");
      setRevisionPreview(null);
      await loadRoadmaps();
    } catch (applyError) {
      setError(applyError instanceof Error ? applyError.message : "Unable to apply roadmap update.");
    } finally {
      setIsApplying(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-display-lg text-ink mb-2">Learning Roadmaps</h1>
        <p className="text-body text-ink-muted">
          Week-wise plans with live progress, history, and agent-guided updates
        </p>
      </div>

      {error && (
        <Card className="border-hairline bg-surface-1">
          <CardContent className="py-4 text-body-sm text-gradient-coral">{error}</CardContent>
        </Card>
      )}

      {isLoading ? (
        <Card className="border-hairline bg-surface-1">
          <CardContent className="py-10 text-center text-body text-ink-muted">Loading roadmaps...</CardContent>
        </Card>
      ) : roadmaps.length === 0 ? (
        <EmptyState
          icon={Map}
          title="No roadmaps yet"
          description="Complete interviews to generate personalized learning roadmaps tailored to your strengths and weaknesses"
        />
      ) : (
        <div className="space-y-6">
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            {roadmaps.map((roadmap) => (
              <button
                key={roadmap.id}
                onClick={() => setSelectedRoadmapId(roadmap.id)}
                className={cn(
                  "rounded-lg border border-hairline bg-surface-1 p-5 text-left transition-colors hover:border-accent-blue/60",
                  selectedRoadmap?.id === roadmap.id && "border-accent-blue"
                )}
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-body font-semibold text-ink">{roadmapText(roadmap.title)}</p>
                    <p className="mt-1 text-caption text-ink-muted">Updated {formatDate(roadmap.updatedAt)}</p>
                  </div>
                  {roadmap.isActive ? (
                    <Badge className="bg-primary text-on-primary">Active</Badge>
                  ) : (
                    <Target className="h-5 w-5 text-ink-muted" />
                  )}
                </div>
                <p className="mt-4 line-clamp-2 text-body-sm text-ink-muted">{roadmapText(roadmap.description)}</p>
                <div className="mt-4 space-y-2">
                  <div className="flex items-center justify-between text-body-sm">
                    <span className="text-ink-muted">Progress</span>
                    <span className="font-medium text-ink">{Math.round(roadmap.progress)}%</span>
                  </div>
                  <Progress value={roadmap.progress} />
                </div>
              </button>
            ))}
          </div>

          {selectedRoadmap && (
            <Card className="border-hairline bg-surface-1">
              <CardHeader>
                <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                  <div>
                    <div className="mb-2 flex flex-wrap items-center gap-2">
                      <CardTitle className="text-headline text-ink">{roadmapText(selectedRoadmap.title)}</CardTitle>
                      {selectedRoadmap.isActive && <Badge className="bg-primary text-on-primary">Active</Badge>}
                    </div>
                    <p className="max-w-3xl text-body text-ink-muted">{roadmapText(selectedRoadmap.description)}</p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {!selectedRoadmap.isActive && (
                      <Button
                        onClick={() => activateRoadmap(selectedRoadmap.id)}
                        className="rounded-lg bg-primary text-on-primary"
                      >
                        <Target className="h-4 w-4" />
                        Make Active
                      </Button>
                    )}
                    <Button
                      variant="outline"
                      onClick={() => {
                        setUpdateOpen(true);
                        setRevisionPreview(null);
                      }}
                      className="rounded-lg border-hairline"
                    >
                      <Edit3 className="h-4 w-4" />
                      Update and Make Active
                    </Button>
                  </div>
                </div>
              </CardHeader>
              <CardContent className="space-y-6">
                <div className="space-y-2">
                  <div className="flex items-center justify-between text-body-sm">
                    <span className="text-ink-muted">Roadmap progress</span>
                    <span className="font-semibold text-ink">{Math.round(selectedRoadmap.progress)}%</span>
                  </div>
                  <Progress value={selectedRoadmap.progress} className="h-2" />
                </div>

                <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
                  {selectedRoadmap.milestones.map((milestone) => (
                    <div key={milestone.id} className="rounded-lg border border-hairline bg-surface-2 p-4">
                      <div className="mb-4 flex items-start gap-3">
                        <CheckCircle2
                          className={cn(
                            "mt-0.5 h-5 w-5 shrink-0",
                            milestone.completed ? "text-semantic-success" : "text-ink-muted"
                          )}
                        />
                        <div>
                          <h3 className="text-body font-semibold text-ink">{roadmapText(milestone.title)}</h3>
                          <p className="mt-1 text-body-sm text-ink-muted">{roadmapText(milestone.description)}</p>
                          <p className="mt-2 text-caption text-ink-muted">Due {formatDate(milestone.dueDate)}</p>
                        </div>
                      </div>

                      <div className="space-y-3">
                        {milestone.tasks.map((task) => (
                          <label
                            key={task.id}
                            className="flex cursor-pointer gap-3 rounded-md border border-hairline bg-surface-1 p-3"
                          >
                            <Checkbox
                              checked={task.completed}
                              onCheckedChange={() => toggleTask(selectedRoadmap.id, milestone.id, task.id)}
                              className="mt-0.5"
                            />
                            <span className="min-w-0">
                              <span
                                className={cn(
                                  "block text-body-sm font-medium",
                                  task.completed ? "text-ink line-through" : "text-ink"
                                )}
                              >
                                {roadmapText(task.title)}
                              </span>
                              {task.description && (
                                <span className="mt-1 block text-caption text-ink-muted">{roadmapText(task.description)}</span>
                              )}
                              <Badge variant="outline" className="mt-2 border-hairline text-ink-muted">
                                {roadmapText(task.priority)}
                              </Badge>
                            </span>
                          </label>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      )}

      <Dialog open={updateOpen} onOpenChange={setUpdateOpen}>
        <DialogContent className="max-w-3xl border border-hairline bg-surface-1 text-ink">
          <DialogHeader>
            <DialogTitle>Update Roadmap</DialogTitle>
            <DialogDescription>
              Describe the change you want. The Roadmap Agent will show pros and cons before applying it.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <Textarea
              value={updateInstructions}
              onChange={(event) => setUpdateInstructions(event.target.value)}
              placeholder="Example: make this roadmap focused on frontend system design and reduce DSA to two days per week."
              className="min-h-28 border-hairline bg-surface-2 text-ink"
            />

            {revisionPreview && (
              <div className="space-y-4 rounded-lg border border-hairline bg-surface-2 p-4">
                <div>
                  <p className="text-body font-semibold text-ink">Agent Preview</p>
                  <p className="mt-1 text-body-sm text-ink-muted">{roadmapText(revisionPreview.summary)}</p>
                </div>

                <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                  <div>
                    <p className="mb-2 text-body-sm font-semibold text-ink">Pros</p>
                    <div className="space-y-2">
                      {revisionPreview.pros.map((item, index) => (
                        <div key={`${item}-${index}`} className="flex gap-2 text-body-sm text-ink-muted">
                          <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-semantic-success" />
                          <span>{roadmapText(item)}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                  <div>
                    <p className="mb-2 text-body-sm font-semibold text-ink">Cons</p>
                    <div className="space-y-2">
                      {revisionPreview.cons.map((item, index) => (
                        <div key={`${item}-${index}`} className="flex gap-2 text-body-sm text-ink-muted">
                          <Target className="mt-0.5 h-4 w-4 shrink-0 text-gradient-coral" />
                          <span>{roadmapText(item)}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>

                <div className="rounded-lg border border-hairline bg-surface-1 p-4">
                  <p className="text-body-sm font-semibold text-ink">{roadmapText(revisionPreview.proposedRoadmap.title)}</p>
                  <p className="mt-1 text-body-sm text-ink-muted">{roadmapText(revisionPreview.proposedRoadmap.description)}</p>
                  <p className="mt-3 text-caption text-ink-muted">
                    {revisionPreview.proposedRoadmap.milestones.length} weeks,{" "}
                    {revisionPreview.proposedRoadmap.milestones.reduce(
                      (total, milestone) => total + milestone.tasks.length,
                      0
                    )} tasks
                  </p>
                </div>
              </div>
            )}
          </div>

          <DialogFooter className="border-hairline bg-surface-2">
            <Button
              variant="outline"
              onClick={() => {
                setUpdateOpen(false);
                setRevisionPreview(null);
              }}
              className="border-hairline"
            >
              Keep Current
            </Button>
            {!revisionPreview ? (
              <Button
                onClick={requestRevisionPreview}
                disabled={!updateInstructions.trim() || isPreviewing}
                className="bg-primary text-on-primary"
              >
                {isPreviewing && <Loader2 className="h-4 w-4 animate-spin" />}
                Preview Update
              </Button>
            ) : (
              <Button onClick={applyRevision} disabled={isApplying} className="bg-primary text-on-primary">
                {isApplying && <Loader2 className="h-4 w-4 animate-spin" />}
                Yes, Update and Make Active
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
