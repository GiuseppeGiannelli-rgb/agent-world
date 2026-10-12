---
name: landing-page
description: Build a complete, responsive landing page in plain HTML, CSS and JavaScript that integrates the team's copy, styles and generated images. Use for websites, landing pages, product pages and portfolios.
---

# Landing page

## Structure
1. `index.html`: header with brand and one call to action, hero (headline, sub-headline, primary button, hero image), 3–5 content sections, social proof, final call to action, footer.
2. `css/style.css`: CSS variables for colours, font stack and radius at the top; mobile-first; one breakpoint around 760px.
3. `js/app.js`: only progressive enhancement (reveal on scroll, mobile menu). The page must work without it.

## Integration rules
- Read `content/` (copy), `css/` (design system) and `assets/` (images) before writing. Use the real copy, never lorem ipsum.
- Reference images with relative paths and meaningful `alt` text.
- Links that open a new tab use `rel="noopener noreferrer"`.
- No external CDNs unless the task asks for them.

## Self-check before finishing
- Every section from the research notes exists.
- No `TODO`, placeholder text or broken relative path.
- Headline and button text match the copy file.
