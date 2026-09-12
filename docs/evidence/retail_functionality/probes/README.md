# Diagnostic probes, not audit cases

Each file here is a throwaway two-case run written while chasing one specific
question during the overnight UAT — does this selector exist, does that route
render, what does the axis of this chart actually contain. They were driven in
the same browser as the audit suites and they are kept because they are
evidence of how a defect was located, but they are NOT part of the functional
result.

Two of them record a FAIL. `probe_axis` failed on
`ElementHandle.inner_text: Node is not an HTMLElement` — which is what it was
written to discover, and which became the fix to the visual suite's axis
reader. `probe_lens` failed the same way, on a selector that did not exist.
Neither is a defect in the product.

The audit result is the JSON files one directory up, and the count in
section G of `docs/RETAIL_OVERNIGHT_HANDOVER.md`.
