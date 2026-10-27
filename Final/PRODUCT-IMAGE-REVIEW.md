# Uniform product image frames

All storefront product photos use a square (1:1) frame, centred with object-fit: contain and a brand cream background. This includes the shop, collections, bestsellers, hero, gifting and story product photos, product detail gallery, thumbnails and cart. Source images and shared product records retain their original dimensions and paths. Future uploads receive the same display treatment automatically.

91 unique public image files from the current catalogue, variants, collections and editorial product photos were downloaded and visually reviewed on 27 October 2026. All 91 loaded. No file aspect ratio was more extreme than 0.6 or 1/0.6. Full-image fitting avoids new cropping, stretching or rotation; it cannot restore parts missing from an original or centre a subject within its existing background.

## Individual review

| Product | Image | Decision needed |
| --- | --- | --- |
| KJ-SPL-903 — Custom Beaded Name Plaque | v2/p21-4.jpg | Narrow plaque occupies a small part of a portrait image with large white margins. Consider trimming the existing margins or a new square product photo. |
| KJ-PRS-209 — Pearl Beaded Clutch, Gold Dot Detail | v2/p8-2.jpg | Product reaches and is cut by the left edge of the source. A replacement original or separately approved background extension is needed for a full-product photo. |
| KJ-APC-403 — Pastel Beaded AirPods Case | v2/p12-4.jpg | Product is small and low in the desk scene. Consider a closer product shot or a reviewed subject crop. |
| KJ-ORG-108 — Pearl Beaded Catch-All Tray | v2/p4-5.jpg | Product is relatively small in a dark room scene. A closer, brighter source would improve visibility. |
| KJ-ORG-110 — Crystal Beaded Tissue Dispenser | v2/p5-3a.png | Existing source is only 400 × 400 pixels. Larger gallery views may look soft; use a higher-resolution original. |

No individual source image was edited.

## Deployment

Based on codex/render-backend, whose storefront HTML matches the live website. Do not merge into the older main branch and deploy it. Deploy this change on the existing shared service after reconciling its branch with codex/render-backend. Backend initialize() already copies Final/index.html into content.homepage on startup, keeping the database-served HTML synchronized. No product data migration is needed because asset references and image bytes are unchanged. The CSS URL has a version query so browsers request the new rules.
