# Standard document text handoff — 2026-11-02

## Decision and verified source

Follow `LIBRECHAT_V088_STANDARD_FIRST_MIGRATION.md`: use LibreChat's existing
document extraction and existing owner-scoped attachment handoff. Do not add
a Foundation PDF/Office parser, model, RAG store or cloud extraction route.

LibreChat moved from `danny-avila/LibreChat` to `LibreChat-AI/LibreChat`
(repository ID 600596928). Fixed upstream source revision:
`e8f3be08623663d4ad7f7241e693c94469b63bb0`.

Verified at that revision:

- `packages/api/src/files/documents/crud.ts`, blob
  `4457a30b3d6c78d312fc72b44e063f67f03d6159`: exported `parseDocument`
  delegates PDF to pdfjs, DOCX to mammoth, spreadsheets to SheetJS and ODT
  to the existing upstream extractor. It rejects unsupported, oversized
  (>15 MB) or empty documents. Foundation does not copy this implementation.
- `packages/api/src/files/index.ts` exports `parseDocument`.
- `api/server/services/Files/process.js`, blob
  `35117ab248e7b6e3ad2cbc36b0940a9d21b4a5c6`: context upload persists
  extracted `text` with server-derived `user`, `tenantId`, `file_id`, `type`
  and filename. Configured extraction and native document fallback belong
  to LibreChat. This source evidence is not proof of live upload acceptance.
- `LibreChatAttachmentLookup` already consumes owner/tenant-selected `text`
  before considering a temporary upload path. `AttachmentHandoff` and the
  existing FILES attachment capability can therefore consume that result.

## Implemented residual gap

The previous adapter accepted a structured document's raw path when no
extracted text existed. The FILES consumer decodes attachment paths as UTF-8
with replacement, so an unextracted PDF/Office binary could appear as a
successful but meaningless text result.

The adapter now raises `DocumentTextUnavailable` for structured document
metadata/suffixes without nonempty extracted text. The fixed read-only Mongo
projection now includes `type` and `filename`, retaining the existing
file-id/user/optional-tenant query authority. MIME/suffix detection is a
mechanical refusal to decode structured formats as text, not model routing
or semantic content classification. Image/VISION paths and plain-text paths
retain their existing contracts. Supported owner-scoped extracted text is
preserved exactly, including Japanese/newlines, even after a temp upload
path has expired. No signature, model, grant or Native request is changed.

## Real M1 probe through GitHub

`scripts/m1_librechat_document_probe.py`:

1. Requires macOS and exactly one running LibreChat image publishing host
   port 3080. Ambiguous/missing runtime or another version blocks explicitly.
2. Runs one disposable Node process inside that existing container, requiring
   installed LibreChat v0.8.8 `@librechat/api.parseDocument`.
3. Generates tiny synthetic PDF, DOCX and XLSX fixtures and calls the actual
   installed standard parser. The probe's Node process denies network
   connection APIs before loading the package. It never enables OCR, RAG,
   embeddings or provider calls, and installs no package or model.
4. Takes only the synthetic extracted text through the actual Foundation
   lookup -> handoff -> FILES path in a disposable host directory, verifies
   byte-for-byte text/readback and denies a foreign owner.
5. Removes its disposable files and outputs only aggregate booleans and
   synthetic text digests. Errors disclose a bounded stage/code, not raw
   exception text, runtime paths, credentials or user documents.

`.github/workflows/m1-document-standard-handoff.yml` runs this on the existing
self-hosted M1 via an owner-authored same-repository PR. It performs no
service restart/cutover, Mongo mutation, private upload, source replacement
inside the production container or Desktop Commander call.

## Acceptance limits

Local tests verify document refusal, standard-text preservation, owner/tenant
query scope, Mongo metadata projection, synthetic fixture construction and
the Foundation half of the handoff. M1 parser acceptance is **unverified
until the dedicated workflow actually succeeds**; a BLOCKED result is not
substituted with a local fixture.

Even a successful parser probe does not establish browser upload -> database
record -> signed request -> actual model answer. That full user journey,
scanned PDF/OCR, layout fidelity, legacy DOC/PowerPoint and other formats
retain separate acceptance. Keep the existing owner/signing and capability
boundaries, and never fall back to raw document bytes merely to claim support.
