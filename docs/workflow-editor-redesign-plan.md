# Creating and editing process workflows

Purpose: define a repeatable workflow, configure each step, review it, and save changes with clear context.

## What is wrong today

The baseline browser captures show a centred title and a full-width input with little hierarchy. Step name uses four numbered circles without labels, although the wizard has seven pages. The form stretches across a laptop; help leads the working section. Production uses left-aligned headings, quiet bordered surfaces and a teal accent. The editor should belong to that workspace.

Scope is the shared seven-page create/edit wizard (`/core/flows/create/*`). The scratch/template chooser, template catalogue and workflow graph viewer stay outside this MR. Existing steps enter the same editor through `id` and `edit` parameters.

## What other products do

| Source | Pattern | Change here |
| --- | --- | --- |
| [MRPeasy routing manual](https://www.mrpeasy.com/resources/user-manual/stock/items/details/routings/) | Named operations and sequence form the routing; subtasks open within an operation. | Keep workflow context and ordered stages visible; keep optional explanations in disclosures. |
| [Katana editing operations](https://support.katanamrp.com/en/articles/5967096-how-to-edit-production-operations) | Operations have their own working area; edits do not automatically rewrite existing manufacturing orders. | Separate working form from guidance and retain the existing future-runs explanation. No autosave is added. |
| [Odoo work centres](https://www.odoo.com/documentation/18.0/applications/inventory_and_mrp/manufacturing/advanced_configuration/using_work_centers.html) | Operations belong within the bill of materials and reference their work centres. | Show the workflow as parent context, with materials and evidence as named stages. Full-page retrieval failed; the official search excerpt supported only the operations/work-centre relationship. |
| [Linear issue creation](https://linear.app/docs/creating-issues) | A focused composer keeps title/content central, optional properties separate and drafts recoverable. | Style 2 makes the active editing area dominant; preserve draft restoration. |
| [Notion database layouts](https://www.notion.com/help/layouts) | Page layouts separate main information, grouped properties and supporting panels. | Style 1 places supporting guidance beside the form; Style 3 gives a document-like reading order. |
| [GOV.UK check answers](https://design-system.service.gov.uk/patterns/check-answers/) | A distinct review stage lets people check details before submitting. | Retain the explicit review and save sequence, with a labelled Review stage. |

These references describe patterns, not comparative usability measurements. No evidence found that a seven-stage manufacturing editor should bypass validation or become an autosaving spreadsheet. The recommendation is a design judgment: Style 1 is the closest match to Production and keeps working content and help visible together.

## Three directions to choose from

| | Style 1: Board | Style 2: Editing desk | Style 3: Document |
| --- | --- | --- | --- |
| Idea | Stages above a form beside contextual guidance | Vertical stage rail; form leads, guidance underneath | One continuous sheet, stages then form then reference |
| Taken from | Production surfaces, Notion panels, Katana working area | Linear composer, MRPeasy sequence | Notion page layout, GOV.UK review |
| Best at | Learning and editing with guidance in view | Focusing on one step at a time | Reviewing a compact specification |
| Gives up | Form width to the guide | Immediate visibility of guidance | Side-by-side context and wide working space |

All share the same fields, saves, drafts, permissions, version guards and stage sequence. The progress display is informational: it does not allow skipping required stages. Styles use shared tokens, support dark theme and stack on phones. A concept switch and tab-local remembered choice are temporary review tools.

## Not in this change

No API, database, calculation, execution-history, exports, permissions or template changes. The separate graph viewer and legacy modal are follow-ups. Slow inventory currently leaves a blank pending list; an explicit loading label is a follow-up, recorded in the screenshots. This delivers part of the UX overhaul's workflow area, not the process-design modularisation roadmap item; neither broad item is marked complete.

## Checks

Capture original editor plus Production and Suppliers. Each concept: existing populated step at phone, tablet, laptop and wall; dark; new/quiet workflow; help open; inputs, outputs, evidence, review and finish. Also drive create/save and edit/save, validation, loading/failure and an in-app round trip. CI tests cover style persistence, landmarks, accessible stage state and narrow/wide overflow. Local pytest and CI monitoring are skipped at the user's request; browser screenshots and static checks remain part of design review.
