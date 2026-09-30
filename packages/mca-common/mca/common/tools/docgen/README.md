# docgen

Documentation for the DCC packages the pipeline sits on, read out of the packages themselves and
written where a language model can use it.

```
python -m mca.common.tools.docgen --version 2025 --output D:/AIDocs
```

That imports PyMel, walks `pymel.core`'s submodules, and writes, per function, a JSON file for a
program to look up and a Markdown file to paste into a model's context - plus one `index.json`
over all of them with a summary and some keywords each.

It needs PyMel importable, which in practice means running it under Maya's own interpreter, and
nothing else. No network.

## What this replaced

It was `doccrawler`, 2,247 lines, and most of it downloaded Autodesk's documentation website and
parsed the HTML: a crawler, an HTML parser, and a second crawler for `maya.cmds`. Its own
documentation called that the less reliable half next to introspection, and it is: a web page can
be restyled, a URL can move, a version can stop being published, and what comes back is the
documentation for whichever version is on the internet rather than the one installed here. The
scraping half has not come across. Nor have the two constants holding a previous employer's depot
path.

The docstring parser had to be rewritten. It read a Sphinx line -

```
:param str path: where to save it
```

- by splitting on `:` and taking the second piece as the parameter's name, so every parameter in
every file came out called `param str path`. A bullet line fared worse: `- path: where to save`
gave the *description* as the name. Parameter names are most of what these files are for.

The index is written once now. It used to be read, scanned and rewritten in full for every
function - two thousand reads and two thousand writes of a file that grew as it went.

## Adding another package

`introspect.module_records(module, name)` takes any module. A `maya.cmds` version would use
`cmds.help(command)` rather than docstrings, since `maya.cmds` carries almost none - that is
introspection too, and it belongs here when something needs it.
