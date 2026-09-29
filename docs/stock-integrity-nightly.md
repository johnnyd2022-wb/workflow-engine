# Nightly stock integrity findings

The `inventory.stock_integrity` system check compares each current lot's opening or
produced quantity with sales, wastage, adjustments, and on-hand stock. It checks that
counted units are whole and that every post-go-live sale without a batch allocation has
an explicit reason in the CRM matching queue. Failures appear in System Findings and
Notifications with actions for Live Inventory or CRM matching.

The check shares the system-findings daily cache. `workflow warm-system-findings`
recomputes it for **all active organisations**, including tenants without recent events.
Inventory mutations invalidate the cache; the next read recomputes it. Xero-only changes
are picked up by the nightly run at the latest.

Install the production timer on the Docker host after deploying a build containing this
check:

```bash
sudo cp deploy/systemd/workflow-stock-integrity.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now workflow-stock-integrity.timer
sudo systemctl list-timers workflow-stock-integrity.timer
```

The service runs the CLI inside `workflow-engine-prod` at 00:05 Pacific/Auckland.
`Persistent=true` catches a missed run after a host restart. To verify a run:

```bash
sudo systemctl start workflow-stock-integrity.service
sudo journalctl -u workflow-stock-integrity.service -n 50 --no-pager
```

If production uses a different container name or Docker binary location, change the
service's `ExecStart` before enabling it. Deploying the MR alone does not enable a host
timer; the installation step is required on each production host.
