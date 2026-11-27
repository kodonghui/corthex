# Walking mobile flows with device agents

Use this for Android screens in stage 12. Follow the coverage and persona passes in [browser-agents.md](browser-agents.md) and the release gate in [12-qa.md](12-qa.md). iOS device walks are not covered yet. Use the host's simulator tool where one is available, such as the Xcode Simulator on macOS, and record the coverage the session can show.

The TC runs and real-device checks (`device`) still apply when you use [optional exploratory testing](12-qa.md#exploratory-testing-optional).

## Devices and tools

- Use Android Virtual Devices (AVDs), remote real devices in Samsung Remote Test Lab or Android Device Streaming, or a phone connected by USB or wireless debugging. Use someone's own phone only with that person's explicit yes.
- Use the first tool the session can reach that can do the step. Start with the host's device tool, then Google's Android CLI for agents (`android`), then `adb` and `uiautomator dump`. Use Maestro to pin flows that work. Check each chosen tool's version and help before every run, including the relevant commands and device selection. Record the tool and version.
- Emulators cover repeatable flows. OEM power saving such as sleeping apps, OEM install blockers such as Auto Blocker, the real notification UI and days of idle need `device` cases. Use a remote real device for what fits in a short session. Use the canary for evidence that needs days on a user's device.

## Parallel runs

Use one tester per device. Check acceleration with `emulator -accel-check` before starting emulators. On Windows use WHPX. The Android Emulator Hypervisor Driver (AEHD) is scheduled to end on 2026-12-31.

Run emulators headless on fixed even ports, for example `emulator -avd <name> -port 5554 -no-window -no-snapshot -no-boot-anim -no-audio`. Allocate a separate AVD and port to each simultaneous tester and address every command with the matching serial, such as `adb -s emulator-5554`.

Start with two devices at once, or fewer when the available devices or the host's agent limit require it. Double after a clean round, up to the host's agent limit. At the first sign of memory pressure, return to the last count that worked. Record that count and date in the stage's `note`.

## Platform behaviour

Plan the states that apply to each platform-behaviour case. In these commands, use `adb -s <serial>` to select the tester's device.

| State | Test setup |
| --- | --- |
| Normal | Start in the device's normal state and leave the platform undisturbed |
| Unplugged with Doze forced | Use `adb shell dumpsys battery unplug` and `adb shell dumpsys deviceidle force-idle`. Restore with `adb shell dumpsys deviceidle unforce` and `adb shell dumpsys battery reset` |
| App standby | Use `adb shell am set-inactive <package> true` and restore the prior inactive setting when done. Android documents `adb shell am set-standby-bucket <package> <bucket>` on Android 9 and later. Read the prior bucket with `am get-standby-bucket` and restore it after the check |
| After a reboot | Reboot the test device and observe how the app behaves as the system starts again |

Record simulated battery, idle and standby evidence as `forced`. A forced run can show how the app handles a state. The gate requires the unforced check in [12-qa.md](12-qa.md#forced-runs).

## Install and update

For an app distributed outside a store, download and install the old version through the device's browser as a user would. Reserve `adb install` for development setup. Use the product's own update path from the browser-installed version. Record the installer with `adb shell dumpsys package <package>` and compare the installed `versionCode` before and after. The update passes when the installed `versionCode` rises to the expected value. Collect the relevant `PackageInstaller` and background-activity-launch lines from logcat.

## Walking a row

Use the same verdicts and impressions as [browser-agents.md](browser-agents.md#walking-a-row). Save a screenshot, an accessibility dump and a logcat excerpt per step. Check the expected state and any effect on data. In the persona pass, give the tester a goal without the navigation steps, such as finding whether there is an update and where to turn updates on. Record what was hard to find. Keep personal data out of screenshots, dumps and logs.
