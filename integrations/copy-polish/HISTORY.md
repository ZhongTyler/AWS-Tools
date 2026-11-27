# Report prompt history and offline verification

Report identity includes the exact prompt. Known snapshots are immutable in report_document.EDITORS: 1.0.0 is the original report editor, 1.1.0 adds explicit literal-quote preservation. The current default prompt bytes are unchanged by this compatibility repair. Prompt changes require a new snapshot and consumer compatibility verification; do not hot-edit a registered prompt during an active batch.

An exported payload records the prepare-time snapshot. A candidate document_key identifies the registered prompt/request used by the native candidate producer. These can differ if an export is later consumed by another executor version. A reconstruction matching a key is identity evidence; it is not an independent capture of the actual HTTP body. Keep that capture unknown when absent. Never relabel a prepare payload as a different actually sent payload.

## Native checking

Existing check automatically matches the receipt's complete document identity against known snapshots. Source keys, review keys, report-review keys, format/scope and mode retain their original meanings. Unknown prompt identities, changed source, context, brief or scope fail. No old receipt is rewritten, no partial becomes pass and live receipts remain live.

To additionally validate an original saved payload against the candidate identity:

~~~text
python -X utf8 -B run.py check game-research --request <original-request.json> --receipt <original-candidate.json> --reviews <original-reviews.json> --payload <original-payload.json>
~~~

Use --payload here only when it belongs to that candidate identity. For an old export and a candidate with a different known prompt, validate the export against its own host document through the API below, then check the candidate separately; the CLI intentionally rejects claiming the old payload belongs to the new candidate.

New candidate generation may explicitly select --editor-version 1.0.0, 1.1.0 or 1.2.0. Existing requests need no field changes. This option does not authorize a call or replay an old call. Historical checking never starts transport. Current new generation defaults to registered 1.2.0; 1.0.0 and 1.1.0 remain immutable known snapshots. This repair does not schedule, retry, upgrade a live mode, or consume model quota.

## Consumer API

~~~python
# Native Research report format only; all calls below are offline.
binding = tool.verify_report_payload(
    workflow, original_request, original_saved_payload,
    expected_document=original_host['document'])
# Returns document, editor_version, canonical_payload_sha256 and evidence scope.
# Compares the complete known prompt, user layout and generation configuration.

prepared = tool.prepare_edit_request(
    original_request, workflow, expected_document=original_candidate['document'])
# Same existing five-tuple; identity at [3], using the matched historical version.

checked = tool.adoption_check(workflow, original_request, original_candidate, original_reviews)
# Same native result and original identity. A missing review remains missing.

identity = tool.checked_report_identity(
    workflow, original_request, checked, export_document=original_host['document'])
# Use before the original consumer's plan. Does not write back or approve content.
~~~

For verify, check the saved request/payload against the original host document after existing source/config/projection drift checks. Keep the host unchanged. For plan, require native pass and approved report review, then check both export and checked document identities against the same original request. Only a registered prompt difference is permitted; all other source, scope and brief identity fields must remain equal. Keep the original mapping, retained metadata and renderer checks. Add the returned identity record to the new plan: export_document, checked_document, export_editor_version, checked_editor_version, prompt_changed_since_export and actual_transport_payload (unknown without independent capture). The plan remains pending the original renderer and review.

A consumer must adopt these calls explicitly. An old adapter that recomputes an old export only with the current prompt still reports drift; this tool update does not edit that consumer or its historical records. Existing public frozen modules keep their original version until their owner publishes a separate update.

## Saved response reassessment and prompt 1.2.0

See [REASSESSMENT.md](REASSESSMENT.md) for the distinct `live_response_reassessment` mode, complete saved-evidence binding and source-bound literal guard. This never changes a parent live partial or issues a new model call. New prompt 1.2.0 makes occurrence preservation and JSON escaping explicit; exact noops in compact `items` are classified as retained only under that new response policy. Unknown/missing/duplicate assignments remain invalid.
