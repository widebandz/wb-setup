# Customer Live Terminal Network

This is the reviewed Fleetdeck terminal-map interface with a VM-local,
metadata-only collector. `page.html` comes from the Fleetdeck authoring preview
(`fleetdeck-authoring` commit `68fabf0`); its board/API links are replaced with
capability-prefixed placeholders and host-specific project labels are generic.
`reader.py` keeps the reviewed schema/privacy projection and stale-source
behavior but invokes only the bundled `snapshot.py` local collector. The
collector and `tm_fleet_common.py` come from the `wb-setup-fleet-graph` stage.

The installer must copy this whole package beside the customer Fleetdeck
`portal_server.py`. Start a separate LaunchAgent with the Fleetdeck directory
as its working directory and `python3 -m customer_fleet_map.server`. Set:

- `FLEETDECK_FLEET_MAP_BIND=127.0.0.1` (the only accepted bind)
- `FLEETDECK_FLEET_MAP_PORT=18790`
- `FLEETDECK_FLEET_HOST_ID=<safe local host alias>` (optional; defaults to `local`)
- `FLEETDECK_BOARD_ORIGIN=https://<this Mac's tailnet name>:8790` (for the
  Fleetdeck phone shell iframe)
- `FLEETDECK_ACCESS_TOKEN_PATH=~/.wideband/fleetdeck/phone-access-token`
  (optional; this is the shared default)

The installer must add a private Tailscale Serve HTTPS route on port `18970`
to `http://127.0.0.1:18790`, without Funnel. The link for the board is
`https://<this Mac's tailnet name>:18970/p/<owner capability>/fleet-map`.
Neither the LaunchAgent nor this package mints the capability; the customer
portal's existing token creator owns it. The token is read on every request,
must be a regular owner-owned file with mode `0600`, and is never logged.

Only `/healthz` is public on loopback. The map page and its JSON API require
the capability. The listener has no POST, tmux keystroke, ttyd, or shell route.
`/api/fleet-map` is the source-backed graph; it never includes pane text or
raw customer messages. New Agent opens the authenticated terminal on `:8783`,
where the customer can create and launch an agent through the shared private
roster. The map remains read only and observes that roster on refresh.

Roster launch receipts appear as `process_observed` and `launch_binding`.
They establish that the recorded launch has a matching current provider
process, without claiming verified identity, sign-in, instruction adoption,
or successful task completion. The guarded customer iMessage runtime's private
configuration contributes an owner-chat route to `wb-head`; the projection
never exposes the owner's address, Messages account, chat IDs, or message text.
Its saved binding remains declared evidence because the transport itself
rechecks the live Messages account and chat before routing or sending.

Probe `/healthz`, then the tokenized page and API over private HTTPS. The API
should return schema `agent-fleet.snapshot.v1`, a current `collected_at`, and a
node for this VM's live head session. A source failure is marked partial or
stale; a green HTTP health response alone does not prove collection.
