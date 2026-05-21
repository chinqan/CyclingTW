---
name: poster-image-generation
description: Generate either a cycling trip Day N poster from day-specific prompt/CSV files, or the overall CyclingTW cover poster from the cover prompt. Use this skill for Day N poster requests, route poster regeneration, or cover poster (封面海報) requests. Always handle rider reference image 主角.png, output naming, and final file saving explicitly.
---

# Poster Image Generation

Generate polished cycling-route posters for this project. This skill supports exactly two modes:

1. **Daily Poster**: create a poster for a specific Day N.
2. **Cover Poster**: create the overall 10-day CyclingTW cover poster.

Do not mix the two modes. If the user's request does not clearly identify Daily Poster or Cover Poster, ask a concise clarification before generating.

## Inputs

**Daily Poster mode**
- `dayN/dayN_prompt.md`: required day-specific visual prompt.
- `dayN/dayN_mymap.csv`: required ordered route/location data for validating geography and route order.
- `主角.png`: required rider and road-bike reference image.

**Cover Poster mode**
- `output/imagegen/cyclingtw-cover_prompt.md`: required cover prompt for the whole 10-day loop.
- `主角.png`: required rider and road-bike reference image.

## Output Paths

**Daily Poster mode**
- Default output: `dayN/dayN_poster.png`
- If it already exists and the user did not explicitly ask to overwrite it, save `dayN/dayN_poster_v2.png`, then `_v3.png`, etc.

**Cover Poster mode**
- Default output: `output/imagegen/cyclingtw-cover_poster.png`
- If it already exists and the user did not explicitly ask to overwrite it, save `output/imagegen/cyclingtw-cover_poster_v2.png`, then `_v3.png`, etc.

Keep generated project assets inside their target project folder before reporting completion.

## Required Safety Gates

### 1. Mode gate

Before generation, state which mode is being used:
- Daily Poster: identify the day number and read both day files.
- Cover Poster: read only the cover prompt.

If mode or day number is unclear, ask the user. Do not infer a day number from unrelated files.

### 2. Rider-reference gate

`主角.png` is mandatory. Confirm it exists before generation.

Before claiming the rider image is used, inspect the available image-generation tool interface:
- If the tool supports image inputs such as `ImagePaths`, `reference_image`, uploaded images, or image-to-image parameters, pass `主角.png` through that image-input mechanism.
- If the tool only supports a text `prompt` and cannot receive image input, automatically use the **Text Approximation fallback**. Do not ask the user unless `主角.png` is missing, unreadable, or cannot be visually inspected.

Never say or imply that `主角.png` was used as an image reference unless it was actually passed to the generation tool as an image input.
When using the fallback, state that Codex visually inspected `主角.png` and converted it into text traits, but the image-generation model did not receive `主角.png` as an image reference.

### Text Approximation fallback

Use this automatically when image input is unavailable but `主角.png` can be visually inspected.

Steps:
- Open or inspect `主角.png` with available image-viewing tools.
- Extract a concise visual description of the rider and road bike: face shape, hairstyle, eyewear if any, jersey color/logos impression, shorts, shoes, bike frame color, handlebar/wheel impression, and distinctive details.
- Add that description to the generation prompt under `【主角文字近似描述】`.
- Remove or soften claims that the generation model is receiving an attached image. Use wording such as `以下是由 Codex 觀察主角.png 後整理出的文字特徵`.
- In the final response, explicitly report that the result is a text-approximation version, not a true image-reference generation.

### 3. Save gate

After generation, the image must be copied or moved into the target output path before final response.

Many image tools save first under a temporary/generated folder such as `.codex/generated_images/...`. When that happens:
- leave the original generated image in place unless the user explicitly asks to delete it;
- copy the generated PNG into the target project output path;
- verify the target file exists with `ls -l`;
- verify dimensions/orientation with a local tool such as `sips`;
- show or visually inspect the final target image when possible.

Do not report completion until the final project file exists at the chosen output path.

## Workflow

1. Determine the mode: Daily Poster or Cover Poster.
2. Read required input files for that mode.
3. Confirm `主角.png` exists.
4. Confirm whether the image-generation tool can actually receive `主角.png` as image input.
5. Build the final prompt and generate the image based on tool capabilities:
   - **If image input is supported**: Pass `主角.png` directly into the tool's image input interface and use the exact contents of the chosen `prompt.md` as the text prompt. Do not add redundant prefix text.
   - **If image input is unavailable**: Inspect `主角.png` visually. Extract a concise visual description of the rider and road bike, append it under a new `【主角文字近似描述】` section in the prompt, and generate using text-only. Ensure the prompt does not falsely claim an image is attached.
8. Save/copy the generated image to the correct target path using the output naming rules.
9. Verify target file existence, dimensions, and aspect orientation.
10. Do a visual quality pass before reporting completion.

## Aspect Ratio Rules

The output tool may ignore the requested aspect ratio, so verify dimensions after generation.

- Cover Poster: target `3:2`, width greater than height.
- Daily Poster: target `3:2`, width greater than height.

If the aspect ratio is wrong, you must dynamically crop the copied project output file after generation before delivery. Because default generation sizes vary (e.g., 1024x1024), **do not hardcode dimensions**. Instead:

1. Identify the generated image dimensions.
2. Calculate the maximum possible center-crop dimensions for the target ratio (`3:2` for both Cover Poster and Daily Poster).
3. Use project-appropriate tooling such as `sips` on macOS to perform the crop.

```bash
# Example: If generated image is 1024x1024 and target is 3:2:
# Height becomes 1024 * (2/3) ≈ 682, Width remains 1024
sips --cropToHeightWidth 682 1024 path/to/poster.png
```

## Quality Checklist

- Final image file exists in the project target path.
- Aspect ratio matches the requested poster type.

## When To Ask The User

Ask before proceeding when:
- the request does not clearly say which mode to use;
- a Daily Poster request does not identify Day N;
- required input files are missing;
- `主角.png` is missing;
- `主角.png` cannot be visually inspected for Text Approximation fallback;
- the target output file exists and overwriting versus versioning is ambiguous;
- generated output has major quality issues and regeneration would materially change the result.

Do not make silent assumptions for these cases.
