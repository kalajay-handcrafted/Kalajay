# Kalajay — brand website

Static site. No build step, no npm install.

## Files

```
Kalajay Website.dc.html   ← the whole site (markup + logic, single file)
support.js                ← runtime it loads (do not edit)
assets/                   ← logo mark + wordmarks (cream version for the footer)
v2/                       ← 61 product photos extracted from the catalog PDF
uploads/                  ← original logo + catalog PDFs (source material)
```

## Run it in VS Code

1. Open this folder in VS Code (`File → Open Folder…`).
2. Install the **Live Server** extension (by Ritwick Dey) if you don't have it.
3. Right-click `Kalajay Website.dc.html` → **Open with Live Server**.

It opens at `http://127.0.0.1:5500/Kalajay%20Website.dc.html` and hot-reloads on save.

No Live Server? Any static server works from this folder:

```bash
python3 -m http.server 5500     # then open http://localhost:5500/Kalajay%20Website.dc.html
# or
npx serve .
```

Opening the file directly with `file://` mostly works but a server is safer. An internet
connection is needed on first load — React and the Google Fonts (Prata, Jost) come from a CDN.

## Editing

Everything lives in `Kalajay Website.dc.html`:

- **Markup** — inside `<x-dc>…</x-dc>`. Sections in order: header, hero, marquee, collections,
  catalogue, story, custom, contact, footer, WhatsApp button, cart drawer, lightbox.
- **Logic** — the `<script type="text/x-dc">` block at the bottom.
  - `CATS` — the nine collections (name, blurb, cover image).
  - `PRODUCTS` — `["Product name", "imageId", "Collection"]`; `imageId` maps to `v2/<id>.jpg`.
    Add a product by dropping a photo in `v2/` and adding one row.
  - `waLink()` — the WhatsApp number (`919740540847`). Change it in one place.
- **Styling** is inline on each element; fonts, resets and the marquee keyframes are in `<helmet>`.

## Notes

- The cart is an *enquiry list*, not checkout — the catalog has no prices. It sends the selected
  items and quantities to WhatsApp as a pre-filled message. Nothing is persisted between reloads;
  add `localStorage` if you want the list to survive a refresh.
- Contact details (phone, email, GST, Instagram) are hard-coded in the `#contact` section and footer.
- Product images are re-compressed to max 700px. Use the originals from the PDF if you need larger.

## Deploying

It's plain static files — drag the folder onto Netlify Drop, or push to GitHub and enable Pages.
Rename `Kalajay Website.dc.html` to `index.html` first so it loads at the root URL.
