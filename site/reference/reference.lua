-- Adapts the pages that `quartodoc build` writes to the site. Two jobs:
--
-- 1. Sphinx roles. The docstrings cross-reference with Sphinx roles
--    (:class:`EventSet`,
--    :func:`~parametric_insurance_design.problem.build_problems`). quartodoc
--    copies them into the pages as they are, and without its interlinks
--    extension they would show as ":class:" next to the code. The filter
--    drops the role and keeps the name as code; a leading "~" keeps the last
--    dotted component only, as in Sphinx.
-- 2. Page titles. The pages have no title metadata, so the browser tab would
--    show the file name, lower-cased. The filter sets `pagetitle` from the
--    page's first heading (e.g. "StepPayout", "API reference").
local ROLES = {
  attr = true, class = true, data = true, exc = true, func = true,
  meth = true, mod = true, obj = true,
}

-- The text before the role if `text` ends with ":role:", else nil.
local function role_prefix(text)
  local prefix, role = text:match("^(.-):(%a+):$")
  if role and ROLES[role] then
    return prefix
  end
  return nil
end

function Inlines(inlines)
  local out = pandoc.List()
  local i = 1
  while i <= #inlines do
    local el, nxt = inlines[i], inlines[i + 1]
    local prefix = el.t == "Str" and role_prefix(el.text) or nil
    if prefix and nxt and nxt.t == "Code" then
      if prefix ~= "" then
        out:insert(pandoc.Str(prefix))
      end
      local name = nxt.text
      if name:sub(1, 1) == "~" then
        name = name:match("([^%.]+)$") or name:sub(2)
      end
      out:insert(pandoc.Code(name))
      i = i + 2
    else
      out:insert(el)
      i = i + 1
    end
  end
  return out
end

function Pandoc(doc)
  -- Quarto has already set `pagetitle` from the file name; replace it.
  if doc.meta.title == nil then
    for _, block in ipairs(doc.blocks) do
      if block.t == "Header" and block.level == 1 then
        doc.meta.pagetitle = pandoc.utils.stringify(block.content)
        break
      end
    end
  end
  return doc
end
