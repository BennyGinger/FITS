# Preprocessing overview

[Guide home](README.md)

Related: [Workflow](first_analysis.md) · [Shared settings](settings/common.md) · [REF/ROI workflow](reference_and_roi_masks.md)

Preprocessing corrects geometry and background before segmentation or measurement.
FIScH runs channel registration, then time registration, then background subtraction;
bypassed steps are omitted.

| Main settings tab | Dedicated settings page | Preview tool |
| --- | --- | --- |
| Frame-shift | [Frame-shift](settings/time_registration.md) | [Time-registration preview](tools/time_registration.md) |
| Channel-shift | [Channel-shift](settings/channel_registration.md) | [Channel-registration preview](tools/channel_registration.md) |
| Background subtraction | [Background subtraction](settings/background_subtraction.md) | [Background preview](tools/background_subtraction.md) |

Registration changes geometry and can require reviewing saved REF/ROI alignment.
Background subtraction changes intensities only. Preview tools save settings;
the pipeline writes full processed outputs.
