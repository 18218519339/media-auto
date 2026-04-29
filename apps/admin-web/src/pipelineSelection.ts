interface SelectableDraft {
  id: number
  source_id: number
}

interface SelectablePipelineItem<TDraft extends SelectableDraft> {
  source: { id: number }
  draft: TDraft | null
}

export function selectActivePipeline<TDraft extends SelectableDraft, TItem extends SelectablePipelineItem<TDraft>>(
  pipeline: TItem[],
  selectedDraft: TDraft | null,
  activeSourceId: number | null
): { item: TItem | null; draft: TDraft | null } {
  if (activeSourceId !== null) {
    const item = pipeline.find(entry => entry.source.id === activeSourceId) ?? null
    const draft =
      selectedDraft?.source_id === activeSourceId
        ? selectedDraft
        : item?.draft ?? null

    return { item, draft }
  }

  if (selectedDraft) {
    return {
      item: pipeline.find(entry => entry.draft?.id === selectedDraft.id) ?? null,
      draft: selectedDraft
    }
  }

  const item = pipeline.find(entry => entry.draft) ?? pipeline[0] ?? null
  return { item, draft: item?.draft ?? null }
}
