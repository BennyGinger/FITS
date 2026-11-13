# Channel-shift

[Guide home](../README.md)

Related: [Preprocessing](../preprocessing.md) · [Channel-registration preview](../tools/channel_registration.md) · [Shared settings](common.md) · [Channel choices](../channels_and_labels.md)

Align exported fluorescence channels to a reference channel. Open
**Preprocess → Channel-shift**. This corrects spatial offsets rather than intensity differences.

## Settings

| Parameter | Practical meaning |
| --- | --- |
| Context | Channel shift handles translation, dual-camera shift accommodates rotation, and complex shift supports a more flexible alignment. |
| Reference channel (required) | The channel that stays fixed while other included channels are aligned to it. Choose one exported channel. |
| Reference frame | The frame used to fit cross-channel alignment; GUI numbering starts at 1. |
| Exclude channels | Leave selected channels unchanged. Multiple selection is allowed. |
| Algorithm / Method (advanced) | Override the context's fitting implementation and transform type when needed. |
| Preview | Compare original and registered channel alignment in the dedicated preview. |

## Output

Writes `proc_array_reg_channel.tif`. Channel registration runs before time
registration. Changed geometry can require reviewing REF/ROI alignment;
intensity changes alone do not cause that geometry dependency.
