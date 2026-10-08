---
name: android
description: Android rules for any product, whatever the engine (native SDL, Godot, other) — launcher icons, touch layer, toolchain, on-device performance and installs. Use when building, exporting, installing or polishing an Android build. Native ports also follow the Android section of `port-release`.
---

# Android

- Toolchain: pinned Gradle wrapper URL and checksum, a compatible AGP, one JDK for `java`/`javac`.
  On JDK 26 the baseline is AGP 9.2 with Gradle 9.4.1; verify a real assembly.
- Launcher icons: Honor's MagicOS launcher draws some adaptive icons unmasked (seen with Godot's
  adaptive icon, which always carries a monochrome layer), so the full 108dp canvas shows as a
  square. Make the foreground the art alone with transparent corners, and bake the shape into the
  background layer: a rounded plate inset 1/16 of the canvas, corner radius about 22% of the plate.
  Masking launchers crop that margin away. Check it on a device beside other apps.
- A release needs an authored touch layer through the same action policy as controllers:
  multi-touch, pause, safe areas, scale-aware hit regions, hidden when a controller is present.
- Release performance is measured on named Android devices (frame-time percentiles, thermals,
  memory, loading, correctness); desktop results are not evidence.
- Installing on the user's phone goes over `adb` (wireless pairing when they send a code); the
  phone may be in use by another session, so never drive its screen without asking.
