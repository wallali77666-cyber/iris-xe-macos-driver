# translator/ — Apple AIR → SPIR-V (Phase D)

Metal shaders compile to **AIR** bitcode. To run them on our Vulkan back end (Mesa ANV),
they must be translated to **SPIR-V**, exactly as NullMoth's translator does for NVK.

Plan: port/adapt **metal2vulkan** (the project NullMoth's LGPL-3.0 translator is based on).
Because that lineage is LGPL-3.0-or-later, whatever lands in this directory will carry the
same license and third-party notices — kept strictly separate from the rest of this repo
(its licenses are listed in the root `README.md` when they are decided).

No code yet; this directory exists so the license boundary and build slot are fixed now.
