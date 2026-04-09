'use client';

import { startTransition, useDeferredValue, useState } from 'react';

type Props = {
  candidateId: string;
  apiBaseUrl: string;
};

async function generateDraft(apiBaseUrl: string, candidateId: string) {
  const response = await fetch(`${apiBaseUrl}/drafts/${candidateId}/generate`, {
    method: 'POST',
  });
  if (!response.ok) {
    throw new Error('Failed to generate draft.');
  }
  return response.json();
}

async function decideDraft(apiBaseUrl: string, draftId: string, decision: 'approve' | 'reject', editedBody: string, operatorFeedback: string) {
  const response = await fetch(`${apiBaseUrl}/approvals/${draftId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      decision,
      edited_body: editedBody || null,
      operator_feedback: operatorFeedback || null,
    }),
  });
  if (!response.ok) {
    throw new Error('Failed to submit approval.');
  }
  return response.json();
}

export function ApprovalActions({ candidateId, apiBaseUrl }: Props) {
  const [draftId, setDraftId] = useState('');
  const [draftBody, setDraftBody] = useState('');
  const [feedback, setFeedback] = useState('');
  const [flash, setFlash] = useState('');
  const deferredDraftBody = useDeferredValue(draftBody);

  return (
    <div className="panel-body">
      <div className="candidate-actions">
        <button
          className="button"
          onClick={() =>
            startTransition(async () => {
              try {
                const payload = await generateDraft(apiBaseUrl, candidateId);
                setDraftId(payload.draft.id);
                setDraftBody(payload.draft.body);
                setFlash('Draft generated.');
              } catch (error) {
                setFlash(error instanceof Error ? error.message : 'Draft generation failed.');
              }
            })
          }
        >
          Generate Draft
        </button>
      </div>
      <textarea
        className="draft-box"
        rows={7}
        value={draftBody}
        onChange={(event) => setDraftBody(event.target.value)}
        placeholder="Generate a draft to review and edit."
      />
      <textarea
        className="draft-box"
        rows={3}
        value={feedback}
        onChange={(event) => setFeedback(event.target.value)}
        placeholder="Operator feedback for rejection or later learning."
      />
      <div className="candidate-actions">
        <button
          className="button"
          disabled={!draftId}
          onClick={() =>
            startTransition(async () => {
              if (!draftId) {
                return;
              }
              try {
                const payload = await decideDraft(
                  apiBaseUrl,
                  draftId,
                  'approve',
                  deferredDraftBody,
                  feedback,
                );
                setFlash(
                  `Approved. Post queued${payload.post_action_id ? ` as ${payload.post_action_id.slice(0, 8)}` : ''}.`,
                );
              } catch (error) {
                setFlash(error instanceof Error ? error.message : 'Approval failed.');
              }
            })
          }
        >
          Approve + Queue Post
        </button>
        <button
          className="button secondary"
          disabled={!draftId}
          onClick={() =>
            startTransition(async () => {
              if (!draftId) {
                return;
              }
              try {
                await decideDraft(apiBaseUrl, draftId, 'reject', deferredDraftBody, feedback);
                setFlash('Rejected draft.');
              } catch (error) {
                setFlash(error instanceof Error ? error.message : 'Rejection failed.');
              }
            })
          }
        >
          Reject
        </button>
      </div>
      {flash ? <div className="flash">{flash}</div> : null}
    </div>
  );
}
