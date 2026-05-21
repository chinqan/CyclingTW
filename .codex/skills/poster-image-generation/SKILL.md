---
name: poster-image-generation
description: Generate either a cycling trip Day N poster from day-specific prompt/CSV files, or the overall CyclingTW cover poster from the cover prompt. Use this skill for Day N poster requests, route poster regeneration, or cover poster (封面海報) requests. Always read the rider prompt 主角.md, merge it with the route/cover prompt, and handle output naming/final file saving explicitly.
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
- `主角.md`: required rider and road-bike character prompt.
- `主角.png`: optional visual reference for human inspection only when needed; do not claim it was passed to image generation unless the tool actually supports image inputs and it was passed.

**Cover Poster mode**
- `output/imagegen/cyclingtw-cover_prompt.md`: required cover prompt for the whole 10-day loop.
- `主角.md`: required rider and road-bike character prompt.
- `主角.png`: optional visual reference for human inspection only when needed; do not claim it was passed to image generation unless the tool actually supports image inputs and it was passed.

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
- Daily Poster: identify the day number and read the day prompt, day CSV, and `主角.md`.
- Cover Poster: read the cover prompt and `主角.md`.

If mode or day number is unclear, ask the user. Do not infer a day number from unrelated files.

### 2. Rider-prompt gate

`主角.md` is mandatory. Confirm it exists before generation and read it in full.

Build the generation prompt by combining:
- the selected route/cover prompt (`dayN/dayN_prompt.md` or `output/imagegen/cyclingtw-cover_prompt.md`);
- a rider section copied from `主角.md`, preferably the `可直接放入產圖 Prompt 的版本` section plus relevant negative constraints.

If the selected prompt already contains a rider section from `主角.md` (for example `【主角提示詞（來自主角.md）】` and `【主角負面限制（來自主角.md）】`), do not duplicate the rider text. Instead, compare it against the current `主角.md`; if the prompt is stale, replace the embedded rider section with the current `主角.md` content before generation.

If the image-generation tool supports image inputs and `主角.png` exists, you may pass `主角.png` as an additional visual reference. Never say or imply that `主角.png` was used as an image reference unless it was actually passed to the generation tool as an image input.

### Rider prompt merge rules

When merging `主角.md` into the generation prompt:
- Add it under a clear heading such as `【主角提示詞（來自主角.md）】`.
- Preserve the rider identity constraints: young female cyclist, black long braid, white helmet, blue reflective sunglasses, black/white cycling kit with bright pink accents, road bike with drop bars.
- Preserve `主角.md` negative constraints unless they conflict with the selected route/cover prompt.
- Remove or soften route/cover prompt language that falsely claims an attached image is the only reference source, such as `【輸入圖片】主角.png`, `請依照我上傳的照片生成角色`, `外觀保留真實臉型`, or `公路車...依照照片`.
- Do not replace the route, geography, day order, lighthouse, title, or aspect-ratio instructions from the selected route/cover prompt.

### Daily prompt merge rules

For Daily Poster mode, the final prompt must keep the day-specific route and scene text from `dayN/dayN_prompt.md` as the authority for locations, actions, landmarks, lighting, and composition.

When the day prompt has not yet been pre-merged with `主角.md`:
- Insert `【主角提示詞來源】`, `【主角提示詞（來自主角.md）】`, and `【主角負面限制（來自主角.md）】` after the aspect-ratio/output-format line when possible.
- Rewrite old image-reference language so the character is based on `主角.md`, not an uploaded photo.
- Rewrite road-bike reference language so the bike appearance follows `主角.md`, not a photo.

When the day prompt has already been pre-merged with `主角.md`:
- Use the pre-merged day prompt directly after confirming the embedded rider section is current.
- Do not append another copy of the rider prompt at the end.

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
2. Read required route/cover input files for that mode. For Daily Poster mode, also read `dayN/dayN_mymap.csv` to validate route order and geography.
3. Confirm `主角.md` exists and read it in full.
4. Build the final prompt by merging the chosen route/cover prompt with the relevant `主角.md` rider prompt section.
5. Confirm whether the image-generation tool can receive `主角.png` as an optional image input. If it can and `主角.png` exists, pass it; otherwise proceed with the merged text prompt only.
6. Generate the image.
7. Save/copy the generated image to the correct target path using the output naming rules.
8. Verify target file existence, dimensions, and aspect orientation.
9. Do a visual quality pass before reporting completion.

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
- `主角.md` is missing;
- the target output file exists and overwriting versus versioning is ambiguous;
- generated output has major quality issues and regeneration would materially change the result.

Do not make silent assumptions for these cases.
