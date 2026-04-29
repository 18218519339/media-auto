import assert from 'node:assert/strict';
import { test } from 'node:test';
import { selectActivePipeline } from '../src/pipelineSelection.js';
const oldDraft = { id: 1, source_id: 1 };
const failedSource = { id: 2 };
const pipeline = [
    { source: { id: 1 }, draft: oldDraft },
    { source: failedSource, draft: null }
];
test('keeps a newly generated failed source active instead of showing the old draft', () => {
    const selection = selectActivePipeline(pipeline, null, failedSource.id);
    assert.equal(selection.item?.source.id, failedSource.id);
    assert.equal(selection.draft, null);
});
test('uses the selected draft when no source is actively being generated', () => {
    const selection = selectActivePipeline(pipeline, oldDraft, null);
    assert.equal(selection.item?.source.id, oldDraft.source_id);
    assert.equal(selection.draft?.id, oldDraft.id);
});
