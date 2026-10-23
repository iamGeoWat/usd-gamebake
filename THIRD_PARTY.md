# Third-party notices

Nothing third-party is vendored in this repository. These are what it builds against or imports:

- **godot-usd** (submodule `extern/godot-usd`, pinned to `9c76c6529dc663d52f064919fc25e1408744b7de`) -- MIT License. The
  patches in `patches/godot-usd/` modify it and are offered under the same license. Its license text:

```
Copyright (c) 2026 Miguel de Icaza (https://github.com/migueldeicaza)

Permission is hereby granted, free of charge, to any person obtaining
a copy of this software and associated documentation files (the
"Software"), to deal in the Software without restriction, including
without limitation the rights to use, copy, modify, merge, publish,
distribute, sublicense, and/or sell copies of the Software, and to
permit persons to whom the Software is furnished to do so, subject to
the following conditions:

The above copyright notice and this permission notice shall be
included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
```

- **godot-cpp** (fetched by `scripts/build_extension.sh`) -- MIT License, © the Godot Engine contributors.
- **OpenUSD** (built by you, see README) -- the Tomorrow Open Source Technology License 1.0 (a modified Apache 2.0), © Pixar;
  its build also installs oneTBB (Apache 2.0).
- **trimesh** -- MIT License. **embreex** -- BSD-style license (© Anthony Scopatz), bundling Intel Embree (Apache 2.0).
- **numpy** -- BSD 3-Clause (plus bundled components under compatible licenses). **scipy** -- BSD 3-Clause.
