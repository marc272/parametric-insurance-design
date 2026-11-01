--[[
Inline a schematic SVG into the page (MAR-166).

    ::: {.schematic src="figures/tail-objective.svg"}
    Caption text, in Markdown.
    :::

becomes a <figure class="schematic"> that holds the SVG's markup and the
caption. Inlined, the SVG's currentColor is the page's text colour, so the
schematic reads in the light and the dark theme. `src` is relative to the site
root (site/). A missing file fails the build.
]]

local function read_svg(src)
  local root = quarto.project.directory
  local path = pandoc.path.join({ root, src })
  local fh = io.open(path, "rb")
  if not fh then
    error("inline-svg.lua: cannot read " .. path)
  end
  local svg = fh:read("a")
  fh:close()
  if not svg:match("^%s*<svg[%s>]") then
    error("inline-svg.lua: " .. src .. " must start with <svg")
  end
  return svg
end

function Div(el)
  if not el.classes:includes("schematic") then
    return nil
  end
  local src = el.attributes["src"]
  if src == nil or src == "" then
    error("inline-svg.lua: a .schematic div needs a src attribute")
  end
  local blocks = pandoc.Blocks({
    pandoc.RawBlock("html", '<figure class="schematic">'),
    pandoc.RawBlock("html", read_svg(src)),
  })
  if #el.content > 0 then
    blocks:insert(pandoc.RawBlock("html", "<figcaption>"))
    blocks:extend(el.content)
    blocks:insert(pandoc.RawBlock("html", "</figcaption>"))
  end
  blocks:insert(pandoc.RawBlock("html", "</figure>"))
  return blocks
end
