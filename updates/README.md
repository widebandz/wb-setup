# Wideband Setup update service

`https://os.wideband.ai/version` is the public, schema-1 JSON feed used by the
native macOS app after the client opts in. The feed contains no client data and
accepts download and history links only from
`github.com/widebandz/wb-setup/releases`.

GitHub Releases is the public binary and version-history authority.
`CHANGELOG.md` is the source history in the repository. GitHub Pages publishes
this directory through `.github/workflows/publish-update-feed.yml`; the Pages
deployment contains the extensionless `version` endpoint, `version.json` for
human inspection, and the branded root page.

For each release:

1. Bump `installer/manifest.json`, `CHANGELOG.md`, `README.md`, and
   `BUILD-MEMORY.md`.
2. Run `./selftest.sh`, build and audit the exact app, and finish the VM/client
   acceptance appropriate to the change.
3. Generate the feed from that exact DMG:

   ```bash
   python3 updates/release_feed.py \
     --artifact dist/Wideband-Setup-unsigned.dmg \
     --channel pilot
   ```

4. Commit and push the versioned source and `updates/version.json`, tag the
   same source version, and create the matching GitHub Release. Upload the DMG
   and `dist/SHA256SUMS.txt`. Never advertise an asset before its release URL
   exists.
5. Confirm the Pages workflow succeeds, then verify both the JSON and the DMG
   checksum from a separate network.

The custom hostname requires a DNS CNAME named `os` pointing to
`widebandz.github.io` and the same custom domain configured in this repository's
Pages settings. Keep the record DNS-only until GitHub has issued the HTTPS
certificate. Do not place secrets in the feed or Pages deployment.
