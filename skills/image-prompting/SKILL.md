---
name: image-prompting
description: Write prompts for image generation models (gpt-image, Flux, SDXL) that produce on-brand, consistent images; plan hero images, illustrations, covers and social visuals.
---

# Image prompting

## Prompt anatomy
`[subject + action] , [setting] , [composition / camera] , [lighting] , [style / medium] , [palette] , [mood] , [quality cues]`

Example: "a barista pouring latte art in a sunlit Milan café, close-up from a low angle, warm morning window light, editorial photography, 35mm, palette of cream, terracotta and espresso brown, calm and inviting, high detail".

## Consistency across a set
- Fix a style suffix and reuse it verbatim in every prompt of the project.
- Take the palette from the design system (`css/style.css` variables).
- Keep the same camera language and lighting for images that sit side by side.

## Avoid
- Text inside images (models render it badly): put text in HTML instead.
- Real people's names, logos and trademarks.
- Lists of 20 adjectives: 8–12 precise cues work better.

## Deliver
Save every image at the requested path and document the final prompts in a markdown file next to them so they can be regenerated.
