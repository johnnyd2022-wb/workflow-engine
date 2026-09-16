# Feature availability contract

Core is the stable shell. Optional products may add workspaces but must never prevent
Core, Inventory, or workflow execution from loading.

- CRM is enabled in every shipped environment. If its blueprint cannot register, Core
  logs the failure, omits CRM navigation, assets, and dashboard links, renders the
  disabled Integrations view instead of redirecting to CRM, and continues.
- Compliant is deployment-gated and subscription-gated. An unsubscribed organisation
  sees no Compliant navigation or actionable links; Core still loads. A failed Compliant
  registration is treated the same way.
- Operational Cases remains mounted for recovery/history, but its JavaScript actions are
  controlled by the `operational-cases-enabled` page metadata. A deployment-wide disable
  or registration failure removes those actions instead of sending users to unavailable
  routes.
- Process Templates are always mounted and use their own per-request profile gate.

`tests/test_base_spa_assets.py` covers an enabled CRM asset, optional-product registration
failure, and an unsubscribed Compliant organisation. Add the equivalent render/asset test
whenever a new optional product is linked from the shared SPA shell.
