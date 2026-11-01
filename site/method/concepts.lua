--[[
Site layer for the method pages (MAR-166).

The pages in site/method/ include the repository's concept docs
(docs/concepts/*.md) with Quarto's include shortcode, so the site never forks
their text. Those files are written for GitHub, so this filter adapts them to
the site without editing them:

- the first level-1 heading becomes the page title, unless the page's front
  matter sets one, and is removed from the body (no duplicate title);
- links between the concept docs point to the matching site pages;
- links to other repository docs (../methodology/, ../reviews/, ...) point to
  the file on GitHub, on main;
- images under figures/ are embedded as data URIs, read from
  docs/concepts/figures/ at render time, so the site needs no copy of them;
- tables and figures are wrapped in .table-scroll and .figure-scroll divs,
  so at phone width they scroll inside their own box instead of widening the
  page (site.scss).

Any other relative link or image raises an error, so a new kind of link in the
concept docs fails the build instead of breaking silently on the site.
]]

local GITHUB = "https://github.com/marc272/parametric-insurance-design"

-- docs/concepts/<file> -> the site page that includes it (site/method/).
local PAGES = {
  ["README.md"] = "index.html",
  ["tail-risk-objective.md"] = "tail-risk-objective.html",
  ["portfolio-calibration.md"] = "portfolio-calibration.html",
  ["combination.md"] = "combination.html",
}

-- site/method/ -> docs/concepts/, relative to this filter file.
local script_dir = pandoc.path.directory(PANDOC_SCRIPT_FILE)
local CONCEPTS_DIR = pandoc.path.normalize(
  pandoc.path.join({ script_dir, "..", "..", "docs", "concepts" })
)

local function is_absolute_url(target)
  return target:match("^%a[%w+.-]*:") ~= nil
end

local function split_fragment(target)
  local path, fragment = target:match("^([^#]*)(#?.*)$")
  return path, fragment
end

local function percent_encode(s)
  return (s:gsub("[^%w%-%._~ ]", function(c)
    return string.format("%%%02X", string.byte(c))
  end):gsub(" ", "%%20"))
end

function Link(el)
  local target = el.target
  if target == "" or is_absolute_url(target) or target:sub(1, 1) == "#" then
    return nil
  end
  local path, fragment = split_fragment(target)
  if PAGES[path] then
    el.target = PAGES[path] .. fragment
    return el
  end
  local rest = path:match("^%.%./(.+)$")
  if rest then
    -- Another folder of docs/: link the file (blob) or the folder (tree).
    local kind = rest:sub(-1) == "/" and "tree" or "blob"
    el.target = GITHUB .. "/" .. kind .. "/main/docs/" .. rest .. fragment
    return el
  end
  error("concepts.lua: unmapped relative link in docs/concepts: " .. target)
end

function Image(el)
  local src = el.src
  if is_absolute_url(src) then
    return nil
  end
  local rel = src:match("^figures/(.+%.svg)$")
  if not rel then
    error("concepts.lua: unmapped image in docs/concepts: " .. src)
  end
  local file_path = pandoc.path.join({ CONCEPTS_DIR, "figures", rel })
  local fh = io.open(file_path, "rb")
  if not fh then
    error("concepts.lua: cannot read " .. file_path)
  end
  local svg = fh:read("a")
  fh:close()
  el.src = "data:image/svg+xml;charset=utf-8," .. percent_encode(svg)
  el.classes:insert("concept-figure")
  return el
end

-- Wide tables scroll inside their own box at phone width (site.scss).
function Table(el)
  return pandoc.Div({ el }, pandoc.Attr("", { "table-scroll" }))
end

-- So do the figures: at phone width they keep a legible size and scroll.
function Figure(el)
  return pandoc.Div({ el }, pandoc.Attr("", { "figure-scroll" }))
end

function Pandoc(doc)
  -- The included file's first level-1 heading is its title.
  local blocks = doc.blocks
  for i, block in ipairs(blocks) do
    if block.t == "Header" and block.level == 1 then
      if doc.meta.title == nil then
        doc.meta.title = block.content
      end
      blocks:remove(i)
      break
    end
  end
  return doc
end
