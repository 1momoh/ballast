# Ballast

Author: **1momoh**

Ballast frees disk space by dropping rebuildable developer and AI caches with a
minimum-regret plan. Its mark is an instrument for making room: a Plimsoll disc
crossed by a waterline that steps upward, with a small ballast weight released
below it. The disc retains its integrity while the weight separates. This makes
the idea of selective release visible without an anchor or ship illustration.

## Construction

The master uses a 128 × 128 square and an 8-unit construction grid. The disc is
centred at (64, 56), with radius 32 and an 8-unit stroke. The waterline runs from
(16, 56) to (96, 56), rises to (96, 40), and ends at (112, 40). The released weight
has vertices (48, 96), (80, 96), (72, 112), and (56, 112). The 4-unit outer
stroke extents are deliberate half-grid boundaries. Flat ends and sharp joins
keep the mark closer to a measured load-line than a soft app glyph.

At 16px, the principal stroke is 1px; the two-unit-high weight and its gap remain
recognisable. Use the master directly at 16px and larger, at a square ratio.
Avoid adding detail or shrinking it below 16px.

## Palette

The Desktop pane supplies semantic theme tokens rather than fixed hex values:
`--ui-text`, `--ui-accent`, and `--ui-danger`. Its `Waterline` component supplies
the disc, horizontal datum, upright scale, and monospace figures. These fixed
brand colours interpret that navy/brass/red direction; they are not extracted
hex values from the pane.

| Colour | Hex | Use |
| --- | --- | --- |
| Deep ink navy | `#101D2B` | Icon tile, banner field, wordmark on light backgrounds |
| Brass | `#C3A36A` | Primary mark, release line, instrument labels |
| Warm paper | `#F1EBDD` | Banner name and tagline |
| Signal red | `#C34E43` | One small limit tick in the banner; reserve for warnings |
| Gauge grey | `#A8B0B5` | Secondary labels |
| Rule navy | `#33414C` | Quiet scale and datum lines |

Keep brass flat. Red is a small signal, never the main logo colour. No gradients,
shadows, bevels, or glossy effects.

## Typography

The wordmark uses locally installed Futura Medium, with its geometric circular
forms. All visible lettering in the delivered SVGs is converted to paths,
including the tagline and small labels: no font installation or remote request
is required. Menlo Regular supplies the instrument labels and monospace figures.
For accompanying interface copy, use `ui-monospace, SFMono-Regular, Menlo,
monospace` for measurements and figures.

The exact tagline is **Drop the weight you won't miss.** The small attribution
is **a Hermes Agent plugin**.

## Clear space and backgrounds

Define **u** as the master stroke width: 8 units, or one sixteenth of its square.
Keep at least **2u** between the visible mark and unrelated content. For the
complete wordmark, use the scaled **2u** around the visible lockup. The supplied
square includes optical padding; add space around the tile when a neighbouring
element would otherwise crowd its perimeter. The wordmark's icon-to-name gap is
fixed; preserve it when scaling.

The colour icon has an opaque square navy field. The wordmark has a transparent
background and navy lettering: place it on warm paper, white, or a similarly
light plain field. For dark contexts, use the brass icon or the light banner
lockup. `ballast-icon-mono.svg` is transparent and uses only `currentColor`,
defaulting to black. Set CSS `color` when embedding it inline, or replace
`currentColor` with a single desired colour for an external image or print.
Do not add a background to the mono geometry unless the application needs one.

## Files

| File | Format / purpose |
| --- | --- |
| `ballast-icon.svg` | 128 × 128 colour master; scales to 16px–1024px and beyond |
| `ballast-icon-mono.svg` | 128 × 128 transparent single-colour master |
| `ballast-wordmark.svg` | 1000 × 256 transparent icon + outlined name |
| `ballast-banner.svg` | 1600 × 400 README/social master |
| `ballast-banner-1500x500.svg` | 1500 × 500 X header composition; extra editable source |
| `ballast-icon-1024.png` | 1024 × 1024 |
| `ballast-icon-512.png` | 512 × 512 |
| `ballast-icon-64.png` | 64 × 64 |
| `ballast-wordmark-2000w.png` | 2000 × 512, transparent |
| `ballast-banner-1600x400.png` | 1600 × 400 |
| `ballast-banner-1500x500.png` | 1500 × 500; composed for this ratio, not stretched |
| `build-brand.swift` | Local CoreText outlining, native SVG rendering, PNG checks |
| `BRAND.md` | This guide |
| `.build/inspection.png` | Visual contact sheet, including actual-size 16px/64px checks |
| `.build/ballast-icon-16.png` | Small-size inspection render |

## Rebuild and verification

Run from this folder on macOS with the existing Swift/AppKit/CoreText tools:

```sh
mkdir -p .build/tmp
TMPDIR="$PWD/.build/tmp" CLANG_MODULE_CACHE_PATH="$PWD/.build/module-cache" SWIFT_MODULECACHE_PATH="$PWD/.build/module-cache" swift build-brand.swift
```

The script outlines local fonts, writes SVGs, exports PNGs through the native
AppKit SVG renderer, reloads every PNG, and asserts its dimensions and non-blank
pixel content. No package install or network access is needed.

The delivered PNGs were checked for dimensions and non-blank output, and visually
inspected for spacing, intact outlines, tagline readability, transparency, and
small-icon legibility. SVG XML was parsed successfully. Validation used the local
macOS renderer; other SVG engines were not separately tested.
