// Single shared explanation of confidence scores. Rendered once
// beside each observations list — never repeated on individual cards.

export const CONFIDENCE_HELP_TEXT =
  'Confidence scores reflect model assessments, not verified ' +
  'probabilities or confirmed accuracy.';

/** Inline score. The shared explanation lives beside the list heading. */
export function ConfidenceScore({ value }: { value: number }) {
  return <span>Confidence Score: {String(value)}</span>;
}

/** The ONE visible confidence explainer per observations list. Render
 *  once beside the list, never once per card. */
export function ConfidenceNote() {
  return (
    <details id="confidence-note" className="text-sm text-slate-600">
      <summary
        className="cursor-pointer text-teal-800 underline"
        title={CONFIDENCE_HELP_TEXT}
      >
        About Confidence Scores
      </summary>
      <p className="mt-1">{CONFIDENCE_HELP_TEXT}</p>
    </details>
  );
}
