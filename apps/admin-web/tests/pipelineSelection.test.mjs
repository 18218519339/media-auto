import assert from 'node:assert/strict'

import { selectActivePipeline } from '../.test-build/pipelineSelection.js'

const oldDraft = { id: 1, source_id: 1 }
const failedSource = { id: 2 }

const pipeline = [
  { source: { id: 1 }, draft: oldDraft },
  { source: failedSource, draft: null }
]

const failedSelection = selectActivePipeline(pipeline, null, failedSource.id)

assert.equal(failedSelection.item?.source.id, failedSource.id)
assert.equal(failedSelection.draft, null)

const selectedDraftSelection = selectActivePipeline(pipeline, oldDraft, null)

assert.equal(selectedDraftSelection.item?.source.id, oldDraft.source_id)
assert.equal(selectedDraftSelection.draft?.id, oldDraft.id)

console.log('pipeline selection tests passed')
