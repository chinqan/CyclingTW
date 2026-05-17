---
name: day-poster-image-generation
description: Generate cycling trip day posters for this project from dayN_prompt.md, dayN_mymap.csv, and the rider reference image 主角.png. Use when the user asks to generate a Day N poster, regenerate a route poster, or create a cycling poster image for a specific day.
---

# Day Poster Image Generation

Generate polished daily cycling-route posters for this project. The poster uses the route prompt in `dayN/dayN_prompt.md`, the route/location data in `dayN/dayN_mymap.csv`, and `主角.png` as the rider and road-bike appearance reference.

## Inputs

- `dayN/dayN_prompt.md`: core poster prompt, including scene, route direction, landmarks, lighting, composition, and aspect ratio.
- `dayN/dayN_mymap.csv`: ordered route/location data for validating geographic order and relative placement.
- `主角.png`: visual reference for the rider's face, hairstyle, kit impression, and road-bike frame/color impression.

## Output

- Default output is `dayN/dayN_poster.png`.
- If that file exists and the user did not explicitly ask to overwrite it, save a versioned sibling such as `dayN/dayN_poster_v2.png`, `dayN/dayN_poster_v3.png`, and so on.
- Keep generated project assets inside the relevant `dayN/` folder before finishing.

## Workflow

1. Determine the requested day number from the user request, such as Day 1, 第1天, or `day1`.
2. Read `dayN/dayN_prompt.md` and `dayN/dayN_mymap.csv`.
3. Confirm `主角.png` exists.
4. Build the final image prompt in this order:

```text
請忽略前面所有聊天上下文內容，僅根據以下提示詞與輸入圖片進行圖像生成。

輸入圖片：以主角.png 作為主角人物與公路車的外觀參考。保留可辨識的真實臉型、五官比例、髮型輪廓、車衣印象與公路車車架/顏色印象。

[Paste the full contents of dayN/dayN_prompt.md here.]
```

5. Use the `imagegen` skill and built-in image generation tool for normal generation.
6. Move or copy the selected generated image into the target `dayN/` folder using the output naming rule above.
7. Verify image dimensions and aspect orientation.
8. Do a visual quality pass before reporting completion.

## Aspect Ratio Rules

The output tool may ignore the requested aspect ratio, so verify dimensions after generation.

- North-south / vertical route: target `2:3`, height greater than width.
- East-west / horizontal route: target `3:2`, width greater than height.

If the aspect ratio is wrong, crop the image after generation before delivery. Use project-appropriate tooling such as `sips` on macOS:

```bash
# Vertical 2:3 example, 1024x1536
sips --resampleWidth 1024 dayN/dayN_poster.png
sips --cropToHeightWidth 1536 1024 dayN/dayN_poster.png

# Horizontal 3:2 example, 1536x1024
sips --resampleHeight 1024 dayN/dayN_poster.png
sips --cropToHeightWidth 1024 1536 dayN/dayN_poster.png
```

## Quality Checklist

- Aspect ratio matches the route direction in `dayN_prompt.md`.
- Rider is the largest main subject where the prompt asks for it.
- Rider face, hairstyle, cycling kit impression, and road-bike impression are recognizable from `主角.png`.
- Anatomy is plausible: no extra limbs, broken hands, or impossible bike contact.
- Road bike has reasonable structure: wheels, handlebar, drivetrain, and frame are coherent.
- Geography is plausible and ordered according to `dayN_mymap.csv`.
- Western-coast routes show the sea on the west side and roads/towns inland.
- Mountain or valley routes show matching landforms such as ridges, valleys, rivers, or passes.
- Key landmarks are represented as miniature models without invented foreign architecture.
- The poster has clear foreground, middle ground, background, and a visible journey/story feeling.
