# SPEC: product_images
status: built
name: Workflow product images
slug: product_images
blueprint: Core product image routes
url_prefix: /api/core

## Description
Workflow designers can add, replace or remove a photo of the finished product. It appears on workflow and batch screens and on finished inventory produced by the workflow.

## Users & permissions
- roles: production.design to upload or remove. production.view to see workflow images. inventory.view to see inherited images through the inventory item endpoint.
- tenant_scoped: yes. The image belongs to an organisation and a workflow. Inheritance joins inventory, execution steps, executions and images within that organisation.

## Acceptance criteria
- AC1: Workflow detail prompts designers to add a final product image. Upload, replacement and removal update Workflow detail, the Workflows list, the Live Batches board and the batch start and step record pages.
- AC2: A finished inventory output with recorded lineage resolves its workflow's current image even when its name differs from the workflow name. Replacement and removal apply to existing output lots.
- AC3: The Stock list, Inventory Live cards and the stock lot detail drawer reserve a fixed thumbnail or preview area. Raw material, WIP and finished goods without a linked image display a neutral placeholder. Thumbnails lazy-load and the upload picker accepts phone photos in supported formats.
- AC4: Upload accepts decoded JPEG, PNG and WebP. It rejects unsupported signatures, MIME mismatches, animated or invalid images, files over 10 MiB, and images over 25 million pixels. A missing or generic binary MIME is accepted if the file signature and decode match a supported format. The server applies camera orientation and re-encodes a scaled image without source metadata.
- AC5: Unauthenticated and unauthorised users cannot read or change images. An authenticated user in another organisation receives 404 for foreign workflows and inventory items. Site-restricted staff cannot use the image routes to bypass the existing stock and workflow endpoint restrictions.

## Data model
- changes: one product_images table with tenant-scoped workflow foreign key and one row per workflow, using database binary storage. No existing rows need a backfill.
- destructive: no on upgrade. Downgrade removes the image table and its uploaded images.

## External surfaces
- Authenticated multipart upload, image GET and image DELETE. Existing CSRF and access policy apply. The normalized image is served from the application origin.

## Out of scope
- Per-item overrides, public images, Producer Hub changes and name-based product matching.

## Assumptions
- ASSUMPTION: Resolve live for final-product lots. When a source execution step is recorded, require a same-tenant terminal step and require both lineage IDs to agree if present. Older final-product lots with only a source execution ID use that execution. Existing unlinked inventory keeps its placeholder.
- ASSUMPTION: Keep one image per workflow. Normalize a still image to WebP at up to 720 pixels on the longest side for all display sizes.
- ASSUMPTION: Workflow image permissions follow workflow design and production visibility. The inventory item route independently follows stock visibility. The new endpoints follow the same site-restricted staff policy as their workflow and stock pages.
