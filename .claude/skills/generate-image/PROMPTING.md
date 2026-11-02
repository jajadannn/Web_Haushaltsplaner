# Prompt Construction for GPT Image 2

Distilled from the official OpenAI Cookbook "GPT Image Generation Models
Prompting Guide". Apply these when turning a user request into the prompt string
passed to `generate-image.sh`. The model is OpenAI **GPT Image 2** (not Google
Imagen): these rules are specific to it.

## Build order (always)

Order matters: the model weights earlier elements more. Build the prompt in this
sequence, using line breaks or labels for anything non-trivial:

1. **Scene / background**: environment, setting
2. **Subject**: main subject, described concretely
3. **Key details**: style, medium, materials, textures
4. **Constraints**: what must NOT change or appear (invariants)
5. **Intended use**: "ad", "UI mock", "infographic", "hero banner", "icon"

## Core levers

| Goal | What to write |
|------|---------------|
| **Photorealism** | Add `photorealistic` / `real photograph` / `taken on a real camera`. Add explicit texture cues (pores, fabric wear, film grain). Use camera language (lens, framing, lighting), not "studio polish". Favor `candid`, `unposed`, `honest`. |
| **Legible text in image** | Put literal text in `"quotes"` or ALL CAPS. Specify font style, size, color, placement. Spell tricky words letter-by-letter. Demand "verbatim, no extra characters". Request high quality for small/dense text. |
| **Layout / composition** | Name framing + viewpoint: close-up, wide, top-down, eye-level, low-angle. State placement: "logo top-right", "subject centered, negative space left". For people: scale, body framing, gaze, object interaction. |
| **Lighting / mood** | soft diffuse, golden hour, high-contrast, coastal daylight, shallow depth of field. |

## Invariants (critical for edits / iterations)

State what stays fixed **explicitly and repeat it on every iteration** to stop
drift. For edits: `change only X` + a full `keep everything else the same` list
(camera angle, lighting, shadows, surrounding objects, brand elements) on each
follow-up.

## Negative constraints

Phrase exclusions as hard invariants, not vague "do not":
`no watermark`, `no extra text`, `no logos/trademarks`, `do not add new
elements`, `no decorative clutter`, `avoid clip art / stock photography`.

## Avoid

Overloading with conflicting or competing elements. Keep one clear central
concept; build supporting details coherently around it. Iterate in small,
single-variable changes rather than rewriting the whole prompt.

## Size / quality (expressed to Codex in natural language)

The skill calls GPT Image 2 through the Codex image tool, so size and quality
are stated in the prompt text rather than as API parameters:

- Append e.g. `Render as a 1536x1024 landscape image.` (or `1024x1024` square,
  `1024x1536` portrait). These are the popular, safe sizes.
- For dense text, infographics, or close portraits, add `high quality`.
- For quick exploration, no quality note is needed (fast default).

## Reusable scaffold

```text
Scene: <environment / backdrop>
Subject: <main subject, concrete>
Style: <medium, look, texture cues>
Composition: <framing, viewpoint, placement>
Lighting: <mood / light>
Text: "<verbatim text>": <font, placement> (omit if none)
Invariants: keep <list of things that must not change>
Avoid: <hard negatives>
Use: <where the asset is used>
Render as a <WxH> image[, high quality].
```

## Source

OpenAI Cookbook, "GPT Image Generation Models Prompting Guide":
https://developers.openai.com/cookbook/examples/multimodal/image-gen-models-prompting-guide
