"""Typst markup for rendering handout grids.

The layout is expressed with native Typst primitives instead of hand-drawn
lines. A handout block is a set of *teams* (the rectangles a sheet is cut into)
laid out in a ``grid`` with gaps between them. Each team is a solid-bordered
``box`` wrapping a ``table`` whose internal separators are dashed and whose
cells are centred (or left-aligned) both horizontally and vertically.

``HandoutGenerator`` fills the ``<...>`` placeholders in ``HEADER`` and then
emits one ``#qlabel`` + ``#handout(...)`` pair per question.
"""

# Document preamble: page geometry, default font and the helper functions
# ``handout`` / ``qlabel``. Placeholders are filled by HandoutGenerator.
HEADER = r"""
#set page(
  width: <PAPERWIDTH>mm,
  height: <PAPERHEIGHT>mm,
  margin: (
    top: <MARGIN_TOP>mm,
    bottom: <MARGIN_BOTTOM>mm,
    left: <MARGIN_LEFT>mm,
    right: <MARGIN_RIGHT>mm,
  ),
)
#set text(font: "<FONT>", size: <FONTSIZE>pt)
#set par(justify: false, leading: 0.55em)
#set block(spacing: 0pt)

#let _solid = 0.8pt + black
#let _dashed = (paint: black, thickness: 0.5pt, dash: "dashed")

// One team: a box of tcols x trows identical cells separated inside by dashed
// lines, each cell's content aligned and vertically centred. Cells are flush so
// each dash sits on a shared edge, centred between the two cells' content (the
// cell inset `pad` is the only gap); this keeps the text optically centred.
// `border` is the outer stroke (solid for a real team, dashed when uncut).
#let _team(border, tcols, trows, cellw, rowh, pad, centered, cells) = box(
  stroke: border,
  inset: 0pt,
  table(
    columns: (cellw,) * tcols,
    rows: (rowh,) * trows,
    inset: pad,
    align: (if centered { center } else { left }) + horizon,
    stroke: (x, y) => (
      left: if x > 0 { _dashed },
      top: if y > 0 { _dashed },
    ),
    ..cells,
  ),
)

// Text is laid out between the font's ascender and descender lines, but its ink
// is not: a capital falls short of the ascender while a descender nearly reaches
// the descender line, so a metrically centred cell reads bottom-heavy. Measuring
// the body again with ink-tight edges gives the slack on each side (summed over
// its lines); half their difference is what centres the ink the eye sees.
#let _ink_shift(body, w) = {
  let h(top, bottom, lead) = measure(box(width: w, {
    set text(top-edge: top, bottom-edge: bottom)
    set par(leading: lead)
    body
  })).height
  let lead = par.leading.to-absolute()
  let lines = if lead == 0pt { 1 } else {
    calc.round((h("ascender", "descender", lead) - h("ascender", "descender", 0pt)) / lead) + 1
  }
  (h("ascender", "bounds", lead) - h("bounds", "descender", lead)) / (2 * lines)
}

// A question block: ncols x nrows cells grouped into (tcols x trows) teams,
// tiled with gaps. Every cell holds the same `cellbody`; a single measurement
// fixes the shared row height to max(content height, strut) + padding. `pad`
// (cell inset) and `strut` (single-line floor) scale per block. `teamed` is
// false when the sheet can't be cut into teams, giving an all-dashed block.
#let handout(ncols, nrows, tcols, trows, gap, cellw, pad, strut, teamed, centered, cellbody) = context {
  let ntc = int(ncols / tcols)
  let ntr = int(nrows / trows)
  let border = if teamed { _solid } else { _dashed }
  let rowh = calc.max(measure(box(width: cellw - 2 * pad, cellbody)).height, strut) + 2 * pad
  let cell = move(dy: -_ink_shift(cellbody, cellw - 2 * pad), cellbody)
  let one = _team(border, tcols, trows, cellw, rowh, pad, centered, (cell,) * (tcols * trows))
  // Left-aligned so the block's left edge lines up with the grey label above it;
  // gaps separate the teams (cells within a team stay flush).
  align(left, grid(
    columns: ntc,
    column-gutter: gap,
    row-gutter: gap,
    ..(one,) * (ntc * ntr),
  ))
}

// Small grey caption sitting just above (and left-aligned with) its block; it is
// sticky so a page break never orphans it from the handout beneath it.
#let qlabel(body) = block(above: <LABEL_ABOVE>mm, below: <LABEL_BELOW>mm,
  sticky: true, text(fill: gray, size: 9pt, body))

// The same caption printed inside each cell instead (`question_label: inside`),
// so a handout carries its question number after it is cut out.
#let clabel(body) = text(fill: gray, size: 9pt, body)

// A block with its number inside prints no caption above it, so nothing would
// keep it off the block before it; this leaves the caption's air instead, and
// drops away at the top of a page like the caption's own spacing.
#let qgap() = v(<LABEL_ABOVE>mm, weak: true)
""".strip()

# Grey caption text, left-aligned directly atop a block.
GREYTEXT = r"""#qlabel[<GREYTEXT>]"""

# The same caption inside every cell of a block (`question_label: inside`).
CELLLABEL = r"""clabel[<CELLLABEL>]"""

# What stands in for the caption above a block that carries its number inside.
QGAP = r"""#qgap()"""

# Image inside a cell, scaled relative to the cell's inner content width.
IMG = r"""image("<IMGPATH>", width: <IMGWIDTH>)"""

IMGWIDTH = r"""<QWIDTH>"""
