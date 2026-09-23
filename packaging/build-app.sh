#!/bin/bash
# Build the Wideband Setup app and shareable DMG in pilot or production trust mode.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROFILE=""
SIGN_IDENTITY="${WIDEBAND_SIGN_IDENTITY:--}"
NOTARY_PROFILE="${WIDEBAND_NOTARY_PROFILE:-}"
while [ "$#" -gt 0 ]; do
  case "$1" in
    --profile)
      [ "$#" -ge 2 ] || { echo "--profile requires a JSON path" >&2; exit 2; }
      PROFILE="$2"
      shift 2
      ;;
    --profile=*) PROFILE="${1#*=}"; shift ;;
    --sign-identity)
      [ "$#" -ge 2 ] || { echo "--sign-identity requires a Developer ID identity" >&2; exit 2; }
      SIGN_IDENTITY="$2"
      shift 2
      ;;
    --sign-identity=*) SIGN_IDENTITY="${1#*=}"; shift ;;
    --notary-profile)
      [ "$#" -ge 2 ] || { echo "--notary-profile requires a keychain profile name" >&2; exit 2; }
      NOTARY_PROFILE="$2"
      shift 2
      ;;
    --notary-profile=*) NOTARY_PROFILE="${1#*=}"; shift ;;
    --help|-h)
      echo "usage: ./packaging/build-app.sh [--profile client-profile.json] [--sign-identity 'Developer ID Application: …'] [--notary-profile keychain-profile]"
      exit 0
      ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done
[ -z "$NOTARY_PROFILE" ] || [ "$SIGN_IDENTITY" != "-" ] \
  || { echo "notarization requires a Developer ID signing identity" >&2; exit 2; }
DIST="$ROOT/dist"
WORK="$(mktemp -d /tmp/wideband-app.XXXXXX)"
APP_NAME="Wideband Setup.app"
APP="$WORK/$APP_NAME"
CONTENTS="$APP/Contents"
RESOURCES="$CONTENTS/Resources"
PAYLOAD="$RESOURCES/wb-setup"
AGENT_APP="$RESOURCES/Wideband Agent.app"
AGENT_CONTENTS="$AGENT_APP/Contents"
ICONSET="$WORK/AppIcon.iconset"
SOURCE_PNG="$WORK/AppIcon-1024.png"
DMG_ROOT="$WORK/dmg"
APP_OUT="$DIST/$APP_NAME"
if [ "$SIGN_IDENTITY" = "-" ]; then
  ARTIFACT_STEM="Wideband-Setup-unsigned"
elif [ -z "$NOTARY_PROFILE" ]; then
  ARTIFACT_STEM="Wideband-Setup-signed-unnotarized"
else
  ARTIFACT_STEM="Wideband-Setup"
fi
ZIP_OUT="$DIST/$ARTIFACT_STEM.zip"
DMG_OUT="$DIST/$ARTIFACT_STEM.dmg"

cleanup() { /bin/rm -rf "$WORK"; }
trap cleanup EXIT INT TERM

[ "$ROOT" != "/" ] && [ -f "$ROOT/setup.py" ] && [ -f "$ROOT/installer/manifest.json" ] \
  || { echo "refusing: repository root was not resolved" >&2; exit 1; }
[ "$(uname -s)" = "Darwin" ] || { echo "the app bundle can only be built on macOS" >&2; exit 1; }
[ -z "$PROFILE" ] || [ -f "$PROFILE" ] || { echo "client profile not found: $PROFILE" >&2; exit 1; }

VERSION="$(/usr/bin/python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["release"])' "$ROOT/installer/manifest.json")"
BUILD_NUMBER="$(date -u '+%Y%m%d%H%M%S')"
BUILD_ID="$VERSION-$BUILD_NUMBER"

/bin/mkdir -p "$CONTENTS/MacOS" "$RESOURCES" "$PAYLOAD" "$ICONSET" "$DIST"
/usr/bin/ditto "$ROOT/packaging/Info.plist" "$CONTENTS/Info.plist"
/usr/bin/plutil -replace CFBundleShortVersionString -string "$VERSION" "$CONTENTS/Info.plist"
/usr/bin/plutil -replace CFBundleVersion -string "$BUILD_NUMBER" "$CONTENTS/Info.plist"
/usr/bin/ditto "$ROOT/packaging/app-launcher" "$RESOURCES/app-launcher"
/usr/bin/ditto "$ROOT/packaging/run-setup.command" "$RESOURCES/run-setup.command"
/bin/chmod 755 "$RESOURCES/app-launcher" "$RESOURCES/run-setup.command"
/usr/bin/xcrun swiftc -parse-as-library -target arm64-apple-macos13.0 \
  -framework AppKit -framework WebKit \
  "$ROOT/packaging/WidebandSetupLauncher.swift" -o "$CONTENTS/MacOS/Wideband Setup"
/bin/chmod 755 "$CONTENTS/MacOS/Wideband Setup"
printf '%s\n' "$BUILD_ID" > "$RESOURCES/build-id.txt"
if [ -n "$PROFILE" ]; then
  /usr/bin/python3 "$ROOT/packaging/render-profile.py" "$PROFILE" "$RESOURCES/client-profile.env"
fi

/usr/bin/rsync -a \
  --exclude '.git/' \
  --exclude 'dist/' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  --exclude '.DS_Store' \
  "$ROOT/" "$PAYLOAD/"

# Bundle the localhost engine so the branded checklist can open immediately on
# a genuinely bare Mac, before Homebrew or Command Line Tools supplies Python.
ENGINE_DIST="$WORK/engine-dist"
ENGINE_WORK="$WORK/engine-work"
PYINSTALLER_ARGS=(
  --clean --noconfirm --onefile --target-arch arm64
  --name wb-setup-engine --distpath "$ENGINE_DIST" --workpath "$ENGINE_WORK"
  --specpath "$WORK"
)
if [ "$SIGN_IDENTITY" != "-" ]; then
  PYINSTALLER_ARGS+=(--codesign-identity "$SIGN_IDENTITY")
fi
PYINSTALLER_ARGS+=("$ROOT/setup.py")
if command -v pyinstaller >/dev/null 2>&1; then
  MACOSX_DEPLOYMENT_TARGET=13.0 pyinstaller "${PYINSTALLER_ARGS[@]}" >/dev/null
elif command -v uv >/dev/null 2>&1; then
  MACOSX_DEPLOYMENT_TARGET=13.0 uvx --from 'pyinstaller==6.22.3' \
    pyinstaller "${PYINSTALLER_ARGS[@]}" >/dev/null
else
  echo "building the bare-Mac setup engine requires pyinstaller or uv" >&2
  exit 1
fi
/usr/bin/ditto "$ENGINE_DIST/wb-setup-engine" "$RESOURCES/wb-setup-engine"
/bin/chmod 755 "$RESOURCES/wb-setup-engine"
# A Developer ID build signs PyInstaller's collected libraries and enables the
# hardened runtime. The ad-hoc pilot deliberately preserves the proven 0.4
# behavior: hardened runtime library validation cannot establish a Team ID for
# an ad-hoc one-file engine after it expands its private libpython at launch.
if [ "$SIGN_IDENTITY" = "-" ]; then
  /usr/bin/codesign --force --sign - "$RESOURCES/wb-setup-engine"
else
  /usr/bin/codesign --force --timestamp --options runtime \
    --sign "$SIGN_IDENTITY" "$RESOURCES/wb-setup-engine"
fi
/usr/bin/codesign --verify --strict "$RESOURCES/wb-setup-engine"
if [ "$SIGN_IDENTITY" = "-" ] \
   && /usr/bin/codesign -dvv "$RESOURCES/wb-setup-engine" 2>&1 | /usr/bin/grep -q 'flags=.*runtime'; then
  echo "refusing: bare-Mac engine unexpectedly enables hardened runtime library validation" >&2
  exit 1
fi
WB_SETUP_ROOT="$PAYLOAD" HOME="$WORK/engine-smoke-home" \
  "$RESOURCES/wb-setup-engine" --help >/dev/null

# Use the canonical Wideband hex-and-planes mark from wideband.ai for the app,
# browser, and disk image rather than maintaining a second installer logo.
/usr/bin/sips -z 1024 1024 "$ROOT/installer/wideband-mark.png" --out "$SOURCE_PNG" >/dev/null

make_icon() {
  local pixels="$1" name="$2"
  /usr/bin/sips -z "$pixels" "$pixels" "$SOURCE_PNG" --out "$ICONSET/$name" >/dev/null
}
make_icon 16   icon_16x16.png
make_icon 32   icon_16x16@2x.png
make_icon 32   icon_32x32.png
make_icon 64   icon_32x32@2x.png
make_icon 128  icon_128x128.png
make_icon 256  icon_128x128@2x.png
make_icon 256  icon_256x256.png
make_icon 512  icon_256x256@2x.png
make_icon 512  icon_512x512.png
make_icon 1024 icon_512x512@2x.png
/usr/bin/iconutil -c icns "$ICONSET" -o "$RESOURCES/AppIcon.icns"

# Build one stable, branded permission principal. macOS privacy grants attach
# to the requesting app/binary, so the browser server must not ask clients to
# approve whichever Terminal or Python happened to launch the installer.
/bin/mkdir -p "$AGENT_CONTENTS/MacOS" "$AGENT_CONTENTS/Resources"
/usr/bin/ditto "$ROOT/agent/Info.plist" "$AGENT_CONTENTS/Info.plist"
/usr/bin/plutil -replace CFBundleShortVersionString -string "$VERSION" "$AGENT_CONTENTS/Info.plist"
/usr/bin/plutil -replace CFBundleVersion -string "$BUILD_NUMBER" "$AGENT_CONTENTS/Info.plist"
/usr/bin/ditto "$RESOURCES/AppIcon.icns" "$AGENT_CONTENTS/Resources/AppIcon.icns"
/usr/bin/xcrun swiftc -parse-as-library -target arm64-apple-macos13.0 \
  -framework AppKit -framework ApplicationServices -framework Carbon -framework CoreGraphics \
  "$ROOT/agent/WidebandAgent.swift" -o "$AGENT_CONTENTS/MacOS/Wideband Agent"
/bin/chmod 755 "$AGENT_CONTENTS/MacOS/Wideband Agent"
if [ "$SIGN_IDENTITY" = "-" ]; then
  /usr/bin/codesign --force --options runtime --entitlements "$ROOT/agent/entitlements.plist" \
    --sign - "$AGENT_APP"
else
  /usr/bin/codesign --force --timestamp --options runtime --entitlements "$ROOT/agent/entitlements.plist" \
    --sign "$SIGN_IDENTITY" "$AGENT_APP"
fi
/usr/bin/codesign --verify --strict "$AGENT_APP"

# Ad-hoc signing adds an integrity seal but uses no Apple Developer identity.
# A configured release build signs the complete nested bundle consistently.
if [ "$SIGN_IDENTITY" = "-" ]; then
  /usr/bin/codesign --force --sign - "$APP"
else
  /usr/bin/codesign --force --timestamp --options runtime --sign "$SIGN_IDENTITY" "$APP"
fi
/usr/bin/codesign --verify --deep --strict "$APP"

if [ -n "$NOTARY_PROFILE" ]; then
  NOTARY_ZIP="$WORK/Wideband-Setup-notary.zip"
  /usr/bin/ditto -c -k --sequesterRsrc --keepParent "$APP" "$NOTARY_ZIP"
  /usr/bin/xcrun notarytool submit "$NOTARY_ZIP" --keychain-profile "$NOTARY_PROFILE" --wait
  /usr/bin/xcrun stapler staple "$APP"
  /usr/bin/xcrun stapler validate "$APP"
fi

if [ -e "$APP_OUT" ]; then
  [ "$APP_OUT" = "$DIST/$APP_NAME" ] || { echo "refusing unsafe app target" >&2; exit 1; }
  /bin/rm -rf "$APP_OUT"
fi
/bin/mv "$APP" "$APP_OUT"

/bin/rm -f \
  "$DIST/Wideband-Setup-unsigned.zip" "$DIST/Wideband-Setup-unsigned.dmg" \
  "$DIST/Wideband-Setup-signed-unnotarized.zip" "$DIST/Wideband-Setup-signed-unnotarized.dmg" \
  "$DIST/Wideband-Setup.zip" "$DIST/Wideband-Setup.dmg" \
  "$DIST/SHA256SUMS.txt"
/usr/bin/ditto -c -k --sequesterRsrc --keepParent "$APP_OUT" "$ZIP_OUT"

/bin/mkdir -p "$DMG_ROOT"
/usr/bin/ditto "$APP_OUT" "$DMG_ROOT/$APP_NAME"
/bin/ln -s /Applications "$DMG_ROOT/Applications"
/usr/bin/ditto "$ROOT/packaging/SHARE-README.txt" "$DMG_ROOT/READ ME FIRST.txt"
/usr/bin/ditto "$ROOT/packaging/Open Privacy & Security.html" "$DMG_ROOT/Open Privacy & Security.html"
/usr/bin/hdiutil create -quiet -volname "Wideband Setup" -srcfolder "$DMG_ROOT" -format UDZO "$DMG_OUT"
if [ "$SIGN_IDENTITY" != "-" ]; then
  /usr/bin/codesign --force --timestamp --sign "$SIGN_IDENTITY" "$DMG_OUT"
fi
if [ -n "$NOTARY_PROFILE" ]; then
  /usr/bin/xcrun notarytool submit "$DMG_OUT" --keychain-profile "$NOTARY_PROFILE" --wait
  /usr/bin/xcrun stapler staple "$DMG_OUT"
  /usr/bin/xcrun stapler validate "$DMG_OUT"
  /usr/sbin/spctl --assess --type open --context context:primary-signature -vv "$DMG_OUT"
fi

(
  cd "$DIST"
  /usr/bin/shasum -a 256 "$(basename "$DMG_OUT")" "$(basename "$ZIP_OUT")" > SHA256SUMS.txt
)

printf '\nBuilt Wideband Setup %s\n' "$BUILD_ID"
printf '  App: %s\n' "$APP_OUT"
printf '  DMG: %s\n' "$DMG_OUT"
printf '  ZIP: %s\n' "$ZIP_OUT"
if [ -n "$PROFILE" ]; then
  printf '  Mode: personalized client build\n'
else
  printf '  Mode: generic pilot (identity collected in native setup popups)\n'
fi
if [ "$SIGN_IDENTITY" = "-" ]; then
  printf '  Trust: ad-hoc signed pilot (Gatekeeper Open Anyway required)\n'
elif [ -n "$NOTARY_PROFILE" ]; then
  printf '  Trust: Developer ID signed, notarized, and stapled\n'
else
  printf '  Trust: Developer ID signed but not notarized\n'
fi
